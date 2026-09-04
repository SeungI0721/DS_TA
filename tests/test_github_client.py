from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
import requests

from github_lab_grader.auth import AuthCredential, AuthSource
from github_lab_grader.github_client import (
    GitHubApiError,
    GitHubClient,
    GitHubClientSettings,
)
from github_lab_grader.models import CollaboratorStatus, GitHubErrorCode


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
REPO = "example-owner/example-repository"


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_response(status=200, data=None, headers: Mapping[str, str] | None = None):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    if data is not None:
        response._content = json.dumps(data).encode("utf-8")
        response.headers.setdefault("Content-Type", "application/json")
    else:
        response._content = b""
    response.url = "https://api.github.com/test"
    return response


def settings(**overrides) -> GitHubClientSettings:
    values = {
        "api_version": "2026-03-10",
        "max_retries": 0,
        "retry_backoff_seconds": 0,
    }
    values.update(overrides)
    return GitHubClientSettings(**values)


def client(outcomes, *, sleeper=lambda _seconds: None, **setting_overrides):
    session = FakeSession(outcomes)
    instance = GitHubClient(
        settings(**setting_overrides),
        session=session,
        sleep=sleeper,
        now=lambda: NOW,
    )
    return instance, session


def repository_json():
    return {
        "id": 123,
        "full_name": REPO,
        "private": True,
        "visibility": "private",
        "default_branch": "main",
        "permissions": {"pull": True, "push": True, "admin": False},
    }


def push_event(event_id="1", created_at="2026-09-03T12:00:00Z"):
    return {
        "id": event_id,
        "type": "PushEvent",
        "actor": {"login": "example-student"},
        "created_at": created_at,
        "payload": {
            "ref": "refs/heads/main",
            "head": "a" * 40,
            "before": "b" * 40,
            "push_id": 99,
        },
    }


def test_successful_repository_metadata_retrieval() -> None:
    api, session = client([make_response(data=repository_json())])
    metadata = api.get_repository(REPO)
    assert metadata.repository_id == 123
    assert metadata.default_branch == "main"
    assert metadata.permissions == {"pull": True, "push": True, "admin": False}
    assert session.calls[0]["timeout"] == (5.0, 20.0)


@pytest.mark.parametrize(
    ("status", "code"),
    [(404, GitHubErrorCode.NOT_FOUND), (401, GitHubErrorCode.AUTH_ERROR)],
)
def test_repository_error_classification(status, code) -> None:
    api, _session = client([make_response(status, {"message": "failure"})])
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is code


def test_permission_403_is_not_retried() -> None:
    api, session = client(
        [make_response(403, {"message": "Resource not accessible by personal access token"})],
        max_retries=2,
    )
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.PERMISSION_ERROR
    assert len(session.calls) == 1


def test_primary_rate_limit_403_is_classified_from_remaining_header() -> None:
    reset = int(NOW.timestamp()) + 120
    api, session = client(
        [
            make_response(
                403,
                {"message": "API rate limit exceeded"},
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)},
            )
        ]
    )
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.RATE_LIMITED
    assert caught.value.rate_limit is not None
    assert caught.value.rate_limit.remaining == 0
    assert len(session.calls) == 1


def test_primary_rate_limit_reset_can_drive_bounded_retry() -> None:
    delays = []
    reset = int(NOW.timestamp()) + 2
    api, session = client(
        [
            make_response(
                403,
                {"message": "API rate limit exceeded"},
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)},
            ),
            make_response(data=repository_json()),
        ],
        sleeper=delays.append,
        max_retries=1,
    )
    assert api.get_repository(REPO).repository_id == 123
    assert delays == [2.0]
    assert len(session.calls) == 2


def test_secondary_rate_limit_403_is_classified_from_retry_after() -> None:
    api, session = client(
        [
            make_response(
                403,
                {"message": "Please retry later."},
                {"Retry-After": "30"},
            )
        ]
    )
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.RATE_LIMITED
    assert caught.value.rate_limit is not None
    assert caught.value.rate_limit.retry_after_seconds == 30.0
    assert len(session.calls) == 1


def test_429_is_rate_limited_without_additional_headers() -> None:
    api, session = client([make_response(429, {"message": "slow down"})])
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.RATE_LIMITED
    assert len(session.calls) == 1


def test_network_timeout_is_classified() -> None:
    api, _session = client([requests.Timeout()])
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.TIMEOUT


def test_network_failure_is_classified() -> None:
    api, _session = client([requests.ConnectionError()])
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.NETWORK_ERROR


def test_transient_5xx_receives_bounded_retry() -> None:
    delays = []
    api, session = client(
        [make_response(503), make_response(data=repository_json())],
        sleeper=delays.append,
        max_retries=1,
        retry_backoff_seconds=0.25,
    )
    assert api.get_repository(REPO).repository_id == 123
    assert len(session.calls) == 2
    assert delays == [0.25]


def test_permanent_4xx_is_not_retried() -> None:
    api, session = client(
        [make_response(422, {"message": "invalid"})],
        max_retries=3,
    )
    with pytest.raises(GitHubApiError):
        api.get_repository(REPO)
    assert len(session.calls) == 1


def test_repository_events_first_page_and_push_normalization() -> None:
    api, session = client([make_response(data=[push_event(), {"id": "2", "type": "WatchEvent"}])])
    result = api.list_repository_events(REPO)
    assert result.coverage.pages_fetched == 1
    assert result.coverage.events_fetched == 2
    assert len(result.push_events) == 1
    push = result.push_events[0]
    assert push.event_id == "1"
    assert push.actor == "example-student"
    assert push.head_sha == "a" * 40
    assert push.push_id == 99
    assert session.calls[0]["params"] == {"per_page": 100}


def test_event_pagination_follows_next_link_and_then_stops() -> None:
    first = make_response(
        data=[{"id": "1", "type": "WatchEvent", "created_at": "2026-09-03T00:00:00Z"}],
        headers={"Link": '<https://api.github.com/repos/example-owner/example-repository/events?page=2>; rel="next"'},
    )
    second = make_response(data=[{"id": "2", "type": "WatchEvent"}])
    api, session = client([first, second])
    result = api.list_repository_events(REPO)
    assert result.coverage.pages_fetched == 2
    assert len(session.calls) == 2
    assert session.calls[1]["params"] is None


def test_event_pagination_marks_300_event_coverage() -> None:
    pages = []
    for page_number in range(1, 4):
        headers = {}
        if page_number < 3:
            headers["Link"] = (
                f'<https://api.github.com/repos/example-owner/example-repository/events?page={page_number + 1}>; rel="next"'
            )
        pages.append(
            make_response(
                data=[{"id": f"{page_number}-{index}", "type": "WatchEvent"} for index in range(100)],
                headers=headers,
            )
        )
    api, session = client(pages)
    result = api.list_repository_events(REPO)
    assert result.coverage.reached_documented_limit is True
    assert result.coverage.events_fetched == 300
    assert len(session.calls) == 3


def test_non_push_and_malformed_push_are_preserved_safely() -> None:
    malformed = {"id": "bad-event", "type": "PushEvent", "actor": {}, "payload": {}}
    api, _session = client([make_response(data=[{"type": "WatchEvent"}, malformed])])
    result = api.list_repository_events(REPO)
    assert result.push_events == ()
    assert len(result.raw_events) == 2
    assert result.malformed_push_events[0].startswith("bad-event:")


def test_collaborator_active() -> None:
    api, _session = client([make_response(204)])
    result = api.check_collaborator(
        REPO, "example-user", repository_accessible=True, caller_has_push=True
    )
    assert result.status is CollaboratorStatus.ACTIVE


def test_reliable_collaborator_missing() -> None:
    api, _session = client([make_response(404)])
    result = api.check_collaborator(
        REPO, "example-user", repository_accessible=True, caller_has_push=True
    )
    assert result.status is CollaboratorStatus.MISSING


def test_ambiguous_collaborator_404_is_unknown() -> None:
    api, _session = client([make_response(404)])
    result = api.check_collaborator(
        REPO, "example-user", repository_accessible=True, caller_has_push=None
    )
    assert result.status is CollaboratorStatus.UNKNOWN


def test_collaborator_permission_error_is_unknown() -> None:
    api, _session = client([make_response(403, {"message": "forbidden"})])
    result = api.check_collaborator(
        REPO, "example-user", repository_accessible=True, caller_has_push=True
    )
    assert result.status is CollaboratorStatus.UNKNOWN
    assert result.error_code is GitHubErrorCode.PERMISSION_ERROR


def test_root_readme_detection_is_case_insensitive_and_root_only() -> None:
    entries = [
        {"type": "dir", "name": "docs", "path": "docs"},
        {"type": "file", "name": "readme.MD", "path": "readme.MD"},
    ]
    assert GitHubClient.find_root_readme(entries) == "readme.MD"
    assert GitHubClient.find_root_readme([{"type": "dir", "name": "README.md"}]) is None
    assert (
        GitHubClient.find_root_readme(
            [{"type": "file", "name": "README.md", "path": "docs/README.md"}]
        )
        is None
    )


def test_readme_retrieval_uses_same_explicit_sha_twice() -> None:
    sha = "c" * 40
    root = [{"type": "file", "name": "README.MD", "path": "README.MD"}]
    encoded = base64.b64encode("테스트 README".encode()).decode()
    api, session = client(
        [
            make_response(data=root),
            make_response(data={"encoding": "base64", "content": encoded, "sha": "d" * 40}),
        ]
    )
    result = api.get_readme_at_sha(REPO, sha)
    assert result.exists is True
    assert result.path == "README.MD"
    assert result.text == "테스트 README"
    assert [call["params"]["ref"] for call in session.calls] == [sha, sha]


def test_readme_missing_at_sha() -> None:
    api, session = client([make_response(data=[{"type": "file", "name": "main.c"}])])
    result = api.get_readme_at_sha(REPO, "c" * 40)
    assert result.exists is False
    assert len(session.calls) == 1


def test_selected_sha_unavailable_never_falls_back() -> None:
    api, session = client([make_response(404)])
    with pytest.raises(GitHubApiError) as caught:
        api.get_readme_at_sha(REPO, "c" * 40)
    assert caught.value.code is GitHubErrorCode.UNRESOLVABLE_REF
    assert len(session.calls) == 1


def test_rate_limit_metadata_parsing() -> None:
    parsed = GitHubClient.parse_rate_limit(
        {
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "42",
            "X-RateLimit-Reset": "1234567890",
            "X-RateLimit-Resource": "core",
            "Retry-After": "2.5",
        }
    )
    assert (parsed.limit, parsed.remaining, parsed.reset_epoch) == (5000, 42, 1234567890)
    assert parsed.retry_after_seconds == 2.5
    assert parsed.resource == "core"


def test_retry_after_is_respected_with_bounded_retry() -> None:
    delays = []
    limited = make_response(429, {"message": "rate limit"}, {"Retry-After": "2"})
    api, session = client(
        [limited, make_response(data=repository_json())],
        sleeper=delays.append,
        max_retries=1,
    )
    assert api.get_repository(REPO).repository_id == 123
    assert delays == [2.0]
    assert len(session.calls) == 2


def test_retry_after_above_configured_bound_is_not_slept_or_retried() -> None:
    delays = []
    api, session = client(
        [
            make_response(
                403,
                {"message": "You have exceeded a secondary rate limit."},
                {"Retry-After": "61"},
            )
        ],
        sleeper=delays.append,
        max_retries=2,
        max_retry_after_seconds=60,
    )
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.RATE_LIMITED
    assert delays == []
    assert len(session.calls) == 1


def test_token_is_not_leaked_into_exception_text() -> None:
    token = "test-secret-token-that-must-not-appear"
    session = FakeSession([make_response(401, {"message": token})])
    api = GitHubClient(
        settings(),
        AuthCredential(token, AuthSource.ENVIRONMENT),
        session=session,
        now=lambda: NOW,
    )
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert token not in str(caught.value)
    assert token not in repr(caught.value)


def test_token_in_rate_limit_body_is_not_leaked_into_error_output() -> None:
    token = "test-secret-token-that-must-not-appear"
    session = FakeSession(
        [
            make_response(
                403,
                {"message": f"API rate limit exceeded for {token}"},
                {"X-RateLimit-Remaining": "0"},
            )
        ]
    )
    api = GitHubClient(
        settings(),
        AuthCredential(token, AuthSource.ENVIRONMENT),
        session=session,
        now=lambda: NOW,
    )
    with pytest.raises(GitHubApiError) as caught:
        api.get_repository(REPO)
    assert caught.value.code is GitHubErrorCode.RATE_LIMITED
    assert token not in str(caught.value)
    assert token not in repr(caught.value)


def test_headers_are_centralized_and_use_configured_api_version() -> None:
    token = "header-test-token"
    session = FakeSession([make_response(data=repository_json())])
    api = GitHubClient(
        settings(),
        AuthCredential(token, AuthSource.ENVIRONMENT),
        session=session,
        now=lambda: NOW,
    )
    api.get_repository(REPO)
    assert session.headers["Accept"] == "application/vnd.github+json"
    assert session.headers["X-GitHub-Api-Version"] == "2026-03-10"
    assert session.headers["Authorization"] == f"Bearer {token}"
