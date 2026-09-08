"""GitHub REST API의 읽기 전용 증거 수집 계층."""

from __future__ import annotations

import base64
import binascii
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .auth import AuthCredential
from .models import (
    CollaboratorCheckResult,
    CollaboratorStatus,
    CommitHistoryResult,
    CommitRecord,
    EventCoverage,
    GitHubErrorCode,
    PushRecord,
    RateLimitInfo,
    ReadmeAtSha,
    RepositoryEventsResult,
    RepositoryMetadata,
)


LOGGER = logging.getLogger(__name__)
REPOSITORY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
TRANSIENT_STATUSES = frozenset({502, 503, 504})
DOCUMENTED_EVENT_LIMIT = 300
MAX_COMMIT_HISTORY_PAGES = 10


@dataclass(frozen=True, slots=True)
class GitHubClientSettings:
    api_version: str
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 20.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    max_retry_after_seconds: float = 60.0
    rate_limit_warning_threshold: int = 100
    base_url: str = "https://api.github.com"

    @classmethod
    def from_global_config(cls, config: Mapping[str, Any]) -> "GitHubClientSettings":
        """config.json의 GitHub 항목을 단일 HTTP 설정으로 변환한다."""

        request = config.get("github_request", {})
        if not isinstance(request, Mapping):
            raise ValueError("github_request must be an object")
        return cls(
            api_version=str(config["github_api_version"]),
            connect_timeout_seconds=float(request.get("connect_timeout_seconds", 5.0)),
            read_timeout_seconds=float(request.get("read_timeout_seconds", 20.0)),
            max_retries=int(request.get("max_retries", 2)),
            retry_backoff_seconds=float(request.get("retry_backoff_seconds", 0.5)),
            max_retry_after_seconds=float(request.get("max_retry_after_seconds", 60.0)),
            rate_limit_warning_threshold=int(request.get("rate_limit_warning_threshold", 100)),
        )

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.api_version):
            raise ValueError("api_version must use YYYY-MM-DD")
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("request timeouts must be positive")
        if self.max_retries < 0 or self.retry_backoff_seconds < 0:
            raise ValueError("retry settings must not be negative")
        if self.max_retry_after_seconds < 0 or self.rate_limit_warning_threshold < 0:
            raise ValueError("rate-limit settings must not be negative")


class GitHubApiError(RuntimeError):
    """응답 본문이나 credential을 포함하지 않는 GitHub API 오류."""

    def __init__(
        self,
        code: GitHubErrorCode,
        operation: str,
        *,
        status_code: int | None = None,
        rate_limit: RateLimitInfo | None = None,
    ) -> None:
        self.code = code
        self.operation = operation
        self.status_code = status_code
        self.rate_limit = rate_limit
        status = f", HTTP {status_code}" if status_code is not None else ""
        super().__init__(f"GitHub API {operation} failed: {code.value}{status}")


class GitHubClient:
    """재사용 가능한 Session으로 GitHub의 읽기 전용 증거를 수집한다."""

    def __init__(
        self,
        settings: GitHubClientSettings,
        credential: AuthCredential | None = None,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.sleep = sleep
        self.now = now
        self.last_rate_limit: RateLimitInfo | None = None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": settings.api_version,
            "User-Agent": "DS-TA-GitHub-Lab-Grader",
        }
        if credential is not None:
            headers["Authorization"] = f"Bearer {credential.token}"
        self.session.headers.update(headers)

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.settings.connect_timeout_seconds, self.settings.read_timeout_seconds)

    def get_authenticated_user(self) -> str:
        """현재 credential의 GitHub login을 읽기 전용으로 확인한다."""

        response = self._get("/user", operation="authenticated user")
        data = self._json_object(response, "authenticated user")
        login = data.get("login")
        if not isinstance(login, str) or not login:
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, "authenticated user")
        return login

    def get_repository(self, repository: str) -> RepositoryMetadata:
        """저장소 접근성과 default branch 등 현재 metadata를 반환한다."""

        repository = self._validate_repository(repository)
        response = self._get(f"/repos/{repository}", operation=f"repository {repository}")
        data = self._json_object(response, f"repository {repository}")
        try:
            repository_id = int(data["id"])
            full_name = str(data["full_name"])
            private = bool(data["private"])
            default_branch = str(data["default_branch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubApiError(
                GitHubErrorCode.INVALID_RESPONSE, f"repository {repository}"
            ) from exc
        if not full_name or not default_branch:
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, f"repository {repository}")
        permissions_data = data.get("permissions")
        permissions = None
        if isinstance(permissions_data, Mapping):
            permissions = {str(key): bool(value) for key, value in permissions_data.items()}
        visibility = data.get("visibility")
        return RepositoryMetadata(
            repository_id=repository_id,
            full_name=full_name,
            private=private,
            visibility=str(visibility) if visibility is not None else None,
            default_branch=default_branch,
            permissions=permissions,
            rate_limit=self.last_rate_limit,
        )

    def list_repository_events(self, repository: str) -> RepositoryEventsResult:
        """Link pagination을 따라 최대 300개의 repository event를 수집한다."""

        repository = self._validate_repository(repository)
        url: str | None = self._url(f"/repos/{repository}/events")
        params: Mapping[str, Any] | None = {"per_page": 100}
        raw_events: list[dict[str, Any]] = []
        page_rate_limits: list[RateLimitInfo] = []
        visited_urls: set[str] = set()
        pages = 0

        while url is not None and len(raw_events) < DOCUMENTED_EVENT_LIMIT:
            if url in visited_urls:
                raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, "event pagination cycle")
            visited_urls.add(url)
            response = self._get_url(url, operation=f"events {repository}", params=params)
            params = None
            pages += 1
            page = self._json_list(response, f"events {repository}")
            if not all(isinstance(event, dict) for event in page):
                raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, f"events {repository}")
            remaining_capacity = DOCUMENTED_EVENT_LIMIT - len(raw_events)
            raw_events.extend(page[:remaining_capacity])
            if self.last_rate_limit is not None:
                page_rate_limits.append(self.last_rate_limit)
            if len(raw_events) >= DOCUMENTED_EVENT_LIMIT:
                break
            url = self._next_link(response)

        pushes: list[PushRecord] = []
        malformed: list[str] = []
        timestamps: list[datetime] = []
        for event in raw_events:
            created_at = self._parse_optional_timestamp(event.get("created_at"))
            if created_at is not None:
                timestamps.append(created_at)
            if event.get("type") != "PushEvent":
                continue
            try:
                pushes.append(self.normalize_push_event(event))
            except ValueError as exc:
                event_id = event.get("id")
                safe_id = str(event_id) if event_id is not None else "<missing-id>"
                malformed.append(f"{safe_id}: {exc}")

        fetched_at = self.now()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        coverage = EventCoverage(
            fetched_at=fetched_at,
            pages_fetched=pages,
            events_fetched=len(raw_events),
            oldest_event_at=min(timestamps) if timestamps else None,
            newest_event_at=max(timestamps) if timestamps else None,
            reached_documented_limit=len(raw_events) == DOCUMENTED_EVENT_LIMIT,
            latency_window_complete=None,
            assignment_window_covered=None,
            notes=(
                ("300 events returned; older history may be truncated",)
                if len(raw_events) == DOCUMENTED_EVENT_LIMIT
                else ()
            ),
        )
        return RepositoryEventsResult(
            raw_events=tuple(raw_events),
            push_events=tuple(pushes),
            malformed_push_events=tuple(malformed),
            coverage=coverage,
            page_rate_limits=tuple(page_rate_limits),
        )

    def list_repository_commits(
        self, repository: str, branch: str, deadline: datetime
    ) -> CommitHistoryResult:
        """명시한 일반 브랜치의 commit history를 제한된 pagination으로 조회한다."""

        repository = self._validate_repository(repository)
        branch = self._validate_ref(branch)
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError("deadline must be timezone-aware")
        url: str | None = self._url(f"/repos/{repository}/commits")
        params: Mapping[str, Any] | None = {
            "sha": branch,
            "per_page": 100,
        }
        commits: list[CommitRecord] = []
        visited: set[str] = set()
        pages = 0
        while url is not None and pages < MAX_COMMIT_HISTORY_PAGES:
            if url in visited:
                raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, "commit pagination cycle")
            visited.add(url)
            response = self._get_url(
                url,
                operation=f"commits {repository}",
                params=params,
                allowed_statuses=(200, 409),
            )
            params = None
            pages += 1
            if response.status_code == 409:
                data = self._json_object(response, f"commits {repository}")
                message = data.get("message")
                if isinstance(message, str) and "git repository is empty" in message.casefold():
                    return CommitHistoryResult((), True, ("repository has no commits",))
                raise GitHubApiError(
                    GitHubErrorCode.API_ERROR,
                    f"commits {repository}",
                    status_code=409,
                    rate_limit=self.last_rate_limit,
                )
            page = self._json_list(response, f"commits {repository}")
            for item in page:
                if not isinstance(item, Mapping):
                    raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, f"commits {repository}")
                commits.append(self.normalize_commit(item, branch))
            url = self._next_link(response)
        complete = url is None
        return CommitHistoryResult(
            tuple(commits),
            complete,
            () if complete else ("commit history pagination limit reached",),
        )

    @staticmethod
    def normalize_commit(item: Mapping[str, Any], branch: str) -> CommitRecord:
        """commit author/committer 날짜를 구분해 정규화한다."""

        sha = item.get("sha")
        commit = item.get("commit")
        if not isinstance(sha, str) or not sha or not isinstance(commit, Mapping):
            raise ValueError("commit SHA or metadata is missing")
        author = commit.get("author")
        committer = commit.get("committer")
        if not isinstance(committer, Mapping):
            raise ValueError("commit committer metadata is missing")
        committer_date = GitHubClient._parse_optional_timestamp(committer.get("date"))
        author_date = (
            GitHubClient._parse_optional_timestamp(author.get("date"))
            if isinstance(author, Mapping)
            else None
        )
        if committer_date is None:
            raise ValueError("commit committer date is missing")
        return CommitRecord(sha, author_date, committer_date, branch)

    @staticmethod
    def normalize_push_event(event: Mapping[str, Any]) -> PushRecord:
        """PushEvent.created_at만을 제출 시각 증거로 정규화한다."""

        if event.get("type") != "PushEvent":
            raise ValueError("event is not a PushEvent")
        actor = event.get("actor")
        payload = event.get("payload")
        if not isinstance(actor, Mapping) or not isinstance(payload, Mapping):
            raise ValueError("actor or payload is missing")
        required = {
            "event_id": event.get("id"),
            "actor": actor.get("login"),
            "created_at": event.get("created_at"),
            "ref": payload.get("ref"),
            "head_sha": payload.get("head"),
            "before_sha": payload.get("before"),
        }
        if any(not isinstance(value, str) or not value for value in required.values()):
            raise ValueError("required PushEvent field is missing")
        try:
            created_at = datetime.fromisoformat(required["created_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at is invalid") from exc
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at is not timezone-aware")
        push_id_value = payload.get("push_id")
        try:
            push_id = int(push_id_value) if push_id_value is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError("push_id is invalid") from exc
        return PushRecord(
            event_id=required["event_id"],
            actor=required["actor"],
            created_at=created_at,
            ref=required["ref"],
            head_sha=required["head_sha"],
            before_sha=required["before_sha"],
            push_id=push_id,
        )

    def check_collaborator(
        self,
        repository: str,
        username: str,
        *,
        repository_accessible: bool,
        caller_has_push: bool | None,
    ) -> CollaboratorCheckResult:
        """현재 collaborator 상태를 확인하며 모호한 404는 UNKNOWN으로 보존한다."""

        repository = self._validate_repository(repository)
        username = self._validate_username(username)
        checked_at = self.now()
        try:
            response = self._get(
                f"/repos/{repository}/collaborators/{quote(username, safe='')}",
                operation=f"collaborator check {repository}",
                allowed_statuses=(204, 404),
            )
        except GitHubApiError as exc:
            uncertain = {
                GitHubErrorCode.AUTH_ERROR,
                GitHubErrorCode.PERMISSION_ERROR,
                GitHubErrorCode.NOT_FOUND,
                GitHubErrorCode.RATE_LIMITED,
            }
            return CollaboratorCheckResult(
                status=CollaboratorStatus.UNKNOWN if exc.code in uncertain else CollaboratorStatus.ERROR,
                checked_at=checked_at,
                rate_limit=exc.rate_limit,
                error_code=exc.code,
                note="API 오류로 collaborator 상태를 확정할 수 없음",
            )
        if response.status_code == 204:
            status = CollaboratorStatus.ACTIVE
            note = None
        elif repository_accessible and caller_has_push is True:
            status = CollaboratorStatus.MISSING
            note = "저장소 접근 및 caller push 권한을 확인한 상태의 404"
        else:
            status = CollaboratorStatus.UNKNOWN
            note = "저장소 접근 또는 caller push 권한이 확정되지 않은 404"
        return CollaboratorCheckResult(status, checked_at, self.last_rate_limit, note=note)

    def get_root_contents_at_ref(
        self, repository: str, ref: str
    ) -> tuple[tuple[dict[str, Any], ...], RateLimitInfo | None]:
        """명시한 ref의 root entry만 조회하며 default branch로 대체하지 않는다."""

        repository = self._validate_repository(repository)
        ref = self._validate_ref(ref)
        response = self._get(
            f"/repos/{repository}/contents/",
            operation=f"root contents {repository} at explicit ref",
            params={"ref": ref},
        )
        data = self._json_list(response, f"root contents {repository} at explicit ref")
        if not all(isinstance(entry, dict) for entry in data):
            raise GitHubApiError(
                GitHubErrorCode.INVALID_RESPONSE, f"root contents {repository} at explicit ref"
            )
        return tuple(data), self.last_rate_limit

    @staticmethod
    def find_root_readme(entries: Sequence[Mapping[str, Any]]) -> str | None:
        """root entry에서 README.md의 대소문자 변형만 탐색한다."""

        matches: list[str] = []
        for entry in entries:
            name = entry.get("name")
            path = entry.get("path")
            if (
                entry.get("type") == "file"
                and isinstance(name, str)
                and name.casefold() == "readme.md"
                and isinstance(path, str)
                and "/" not in path
                and "\\" not in path
                and path.casefold() == name.casefold()
            ):
                matches.append(path)
        if len(matches) > 1:
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, "ambiguous root README")
        return matches[0] if matches else None

    def get_readme_at_sha(self, repository: str, sha: str) -> ReadmeAtSha:
        """동일한 명시적 SHA로 root 탐색과 README content 조회를 수행한다."""

        repository = self._validate_repository(repository)
        sha = self._validate_ref(sha)
        rate_limits: list[RateLimitInfo] = []
        try:
            entries, root_rate = self.get_root_contents_at_ref(repository, sha)
        except GitHubApiError as exc:
            if exc.code is GitHubErrorCode.NOT_FOUND:
                raise GitHubApiError(
                    GitHubErrorCode.UNRESOLVABLE_REF,
                    f"root contents {repository} at selected SHA",
                    status_code=exc.status_code,
                    rate_limit=exc.rate_limit,
                ) from exc
            raise
        if root_rate is not None:
            rate_limits.append(root_rate)
        path = self.find_root_readme(entries)
        if path is None:
            return ReadmeAtSha(False, sha, rate_limits=tuple(rate_limits))
        try:
            response = self._get(
                f"/repos/{repository}/contents/{quote(path, safe='/')}",
                operation=f"README {repository} at selected SHA",
                params={"ref": sha},
            )
        except GitHubApiError as exc:
            if exc.code is GitHubErrorCode.NOT_FOUND:
                raise GitHubApiError(
                    GitHubErrorCode.UNRESOLVABLE_REF,
                    f"README {repository} at selected SHA",
                    status_code=exc.status_code,
                    rate_limit=exc.rate_limit,
                ) from exc
            raise
        if self.last_rate_limit is not None:
            rate_limits.append(self.last_rate_limit)
        data = self._json_object(response, f"README {repository} at selected SHA")
        content = data.get("content")
        encoding = data.get("encoding")
        if not isinstance(content, str) or encoding != "base64":
            raise GitHubApiError(
                GitHubErrorCode.INVALID_RESPONSE, f"README {repository} at selected SHA"
            )
        try:
            raw = base64.b64decode("".join(content.split()), validate=True)
            text = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise GitHubApiError(
                GitHubErrorCode.INVALID_RESPONSE, f"README {repository} at selected SHA"
            ) from exc
        blob_sha = data.get("sha")
        if not isinstance(blob_sha, str) or not blob_sha:
            raise GitHubApiError(
                GitHubErrorCode.INVALID_RESPONSE, f"README {repository} at selected SHA"
            )
        return ReadmeAtSha(True, sha, path, blob_sha, raw, text, tuple(rate_limits))

    def _get(
        self,
        path: str,
        *,
        operation: str,
        params: Mapping[str, Any] | None = None,
        allowed_statuses: tuple[int, ...] = (200,),
    ) -> requests.Response:
        return self._get_url(
            self._url(path),
            operation=operation,
            params=params,
            allowed_statuses=allowed_statuses,
        )

    def _get_url(
        self,
        url: str,
        *,
        operation: str,
        params: Mapping[str, Any] | None = None,
        allowed_statuses: tuple[int, ...] = (200,),
    ) -> requests.Response:
        self._validate_api_url(url)
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.Timeout as exc:
                if attempt < self.settings.max_retries:
                    self._backoff(attempt)
                    continue
                raise GitHubApiError(GitHubErrorCode.TIMEOUT, operation) from exc
            except requests.RequestException as exc:
                if attempt < self.settings.max_retries:
                    self._backoff(attempt)
                    continue
                raise GitHubApiError(GitHubErrorCode.NETWORK_ERROR, operation) from exc

            rate_limit = self.parse_rate_limit(response.headers)
            self.last_rate_limit = rate_limit
            self._warn_on_low_rate_limit(rate_limit)
            if response.status_code in allowed_statuses:
                return response

            rate_limited = self._is_rate_limited(response, rate_limit)
            if rate_limited:
                retry_after = self._rate_limit_retry_delay(response, rate_limit)
                if (
                    retry_after is not None
                    and retry_after <= self.settings.max_retry_after_seconds
                    and attempt < self.settings.max_retries
                ):
                    self.sleep(retry_after)
                    continue
                raise GitHubApiError(
                    GitHubErrorCode.RATE_LIMITED,
                    operation,
                    status_code=response.status_code,
                    rate_limit=rate_limit,
                )
            if response.status_code in TRANSIENT_STATUSES and attempt < self.settings.max_retries:
                self._backoff(attempt)
                continue
            raise GitHubApiError(
                self._error_code_for_status(response.status_code),
                operation,
                status_code=response.status_code,
                rate_limit=rate_limit,
            )
        raise AssertionError("unreachable retry state")

    def _backoff(self, attempt: int) -> None:
        self.sleep(self.settings.retry_backoff_seconds * (2**attempt))

    def _warn_on_low_rate_limit(self, rate_limit: RateLimitInfo) -> None:
        if (
            rate_limit.remaining is not None
            and rate_limit.remaining <= self.settings.rate_limit_warning_threshold
        ):
            LOGGER.warning(
                "GitHub REST API 잔여 요청 수가 낮습니다: remaining=%s, reset_epoch=%s",
                rate_limit.remaining,
                rate_limit.reset_epoch,
            )

    @staticmethod
    def parse_rate_limit(headers: Mapping[str, str]) -> RateLimitInfo:
        """GitHub rate-limit header를 누락 허용 metadata로 변환한다."""

        lowered = {str(key).lower(): str(value) for key, value in headers.items()}

        def integer(name: str) -> int | None:
            try:
                return int(lowered[name]) if name in lowered else None
            except ValueError:
                return None

        retry_after = None
        if "retry-after" in lowered:
            try:
                retry_after = max(0.0, float(lowered["retry-after"]))
            except ValueError:
                retry_after = None
        return RateLimitInfo(
            limit=integer("x-ratelimit-limit"),
            remaining=integer("x-ratelimit-remaining"),
            reset_epoch=integer("x-ratelimit-reset"),
            retry_after_seconds=retry_after,
            resource=lowered.get("x-ratelimit-resource"),
        )

    @staticmethod
    def _is_rate_limited(response: requests.Response, rate_limit: RateLimitInfo) -> bool:
        if response.status_code not in {403, 429}:
            return False
        if response.status_code == 429:
            return True
        if rate_limit.remaining == 0 or rate_limit.retry_after_seconds is not None:
            return True
        return GitHubClient._has_rate_limit_message(response)

    def _rate_limit_retry_delay(
        self,
        response: requests.Response,
        rate_limit: RateLimitInfo,
    ) -> float | None:
        """공식 header 우선순위에 따라 제한된 재시도 대기 시간을 계산한다."""

        if rate_limit.retry_after_seconds is not None:
            return rate_limit.retry_after_seconds
        if rate_limit.remaining == 0 and rate_limit.reset_epoch is not None:
            return max(0.0, rate_limit.reset_epoch - self.now().timestamp())

        # Secondary rate limit은 reset 시각이 제공되지 않을 수 있다. GitHub가
        # 명시한 최소 대기 60초도 설정 상한을 통과할 때만 실제 재시도한다.
        if response.status_code == 429 or self._has_rate_limit_message(response):
            return 60.0
        return None

    @staticmethod
    def _has_rate_limit_message(response: requests.Response) -> bool:
        try:
            data = response.json()
        except ValueError:
            return False
        message = data.get("message", "") if isinstance(data, Mapping) else ""
        normalized = str(message).casefold().replace("-", " ")
        return "rate limit" in normalized

    @staticmethod
    def _error_code_for_status(status_code: int) -> GitHubErrorCode:
        if status_code == 401:
            return GitHubErrorCode.AUTH_ERROR
        if status_code == 403:
            return GitHubErrorCode.PERMISSION_ERROR
        if status_code == 404:
            return GitHubErrorCode.NOT_FOUND
        return GitHubErrorCode.API_ERROR

    @staticmethod
    def _json_object(response: requests.Response, operation: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, operation) from exc
        if not isinstance(data, dict):
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, operation)
        return data

    @staticmethod
    def _json_list(response: requests.Response, operation: str) -> list[Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, operation) from exc
        if not isinstance(data, list):
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, operation)
        return data

    def _next_link(self, response: requests.Response) -> str | None:
        next_link = response.links.get("next", {}).get("url")
        if next_link is None:
            return None
        if not isinstance(next_link, str):
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, "event pagination")
        self._validate_api_url(next_link)
        return next_link

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _validate_api_url(self, url: str) -> None:
        expected = urlparse(self.settings.base_url)
        actual = urlparse(url)
        if actual.scheme != expected.scheme or actual.netloc != expected.netloc:
            raise GitHubApiError(GitHubErrorCode.INVALID_RESPONSE, "pagination URL")

    @staticmethod
    def _validate_repository(repository: str) -> str:
        if not isinstance(repository, str) or repository.count("/") != 1:
            raise ValueError("repository must use owner/repository format")
        owner, name = repository.split("/", 1)
        GitHubClient._validate_username(owner)
        if not REPOSITORY_NAME_PATTERN.fullmatch(name):
            raise ValueError("repository name is invalid")
        return repository

    @staticmethod
    def _validate_username(username: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username):
            raise ValueError("username is invalid")
        return username

    @staticmethod
    def _validate_ref(ref: str) -> str:
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("ref must not be empty")
        return ref

    @staticmethod
    def _parse_optional_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
