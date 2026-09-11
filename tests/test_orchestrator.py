"""학생 및 section/week orchestration의 offline integration 테스트."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from github_lab_grader.github_client import GitHubApiError
from github_lab_grader.models import (
    CollaboratorCheckResult,
    CollaboratorStatus,
    CommitHistoryResult,
    CommitRecord,
    CourseConfig,
    EventCoverage,
    GitHubErrorCode,
    GradingRules,
    GradingStatus,
    PathGroupMatch,
    PushRecord,
    ReadmeAtSha,
    ReadmeStatus,
    RepositoryPathAtSha,
    RepositoryPathsAtSha,
    RequiredPathGroup,
    RepositoryEventsResult,
    RepositoryMetadata,
    ScoreRules,
    SectionDeadline,
    Student,
    SubmissionStatus,
    SubmissionEvidenceSource,
    SubmissionEvidenceType,
    WeeklyRubric,
    ScoringMode,
)
from github_lab_grader.orchestrator import GradingOrchestrator


START = datetime(2026, 9, 1, tzinfo=UTC)
SCHEDULED = datetime(2026, 9, 2, tzinfo=UTC)
EFFECTIVE = datetime(2026, 9, 3, tzinfo=UTC)
LATE_END = datetime(2026, 9, 8, tzinfo=UTC)
GRADED = LATE_END + timedelta(hours=7)
HEAD = "a" * 40


def student(index: int = 1) -> Student:
    return Student(
        "01",
        f"EXAMPLE{index:03d}",
        f"Example Student {index}",
        f"student-example-{index}",
        f"example-owner/repository-{index}",
    )


def course() -> CourseConfig:
    return CourseConfig(
        1,
        "2026-2",
        "Data Structures",
        "example-professor",
        "example-assistant",
        "Asia/Seoul",
        ("01", "02"),
        14,
        10.0,
        "2026-03-10",
        6,
        30,
        {},
    )


def rubric(*, branch: str = "default", late_end=LATE_END) -> WeeklyRubric:
    return WeeklyRubric(
        1,
        "Example Week",
        1.0,
        branch,
        True,
        {"01": SectionDeadline(START, SCHEDULED, EFFECTIVE, late_end)},
        GradingRules(),
        ScoreRules(1.0, 0.5, 0.0),
    )


def week1_rubric() -> WeeklyRubric:
    return WeeklyRubric(
        1,
        "Week 1 Binary",
        1.0,
        "default",
        True,
        {
            "01": SectionDeadline(START, EFFECTIVE, EFFECTIVE, None),
            "02": SectionDeadline(EFFECTIVE, EFFECTIVE, EFFECTIVE, None),
        },
        GradingRules(
            professor_collaborator_required=True,
            assistant_collaborator_required=True,
            readme_required=True,
            student_id_required=False,
            student_name_required=False,
            scoring_mode=ScoringMode.BINARY,
            use_late_window=False,
            enforce_submission_window_start=False,
            enforce_submission_branch=False,
            submission_evidence_sources=(
                SubmissionEvidenceType.PUSH_EVENT,
                SubmissionEvidenceType.COMMIT_HISTORY,
            ),
            required_path_groups=(
                RequiredPathGroup(
                    "repository_root_readme",
                    PathGroupMatch.ANY,
                    ("README.md",),
                    "ROOT_README_MISSING",
                ),
                RequiredPathGroup(
                    "week_project_readme",
                    PathGroupMatch.ANY,
                    ("week01/README.md", "week01-01/README.md"),
                    "PROJECT_README_MISSING",
                ),
            ),
        ),
        ScoreRules(1.0, 0.0, 0.0),
    )


def run_week1(item: Student, scenario: Scenario):
    github = FakeGitHub({item.repository: scenario})
    result = GradingOrchestrator(github, course(), now=lambda: GRADED).grade_student(
        item, week1_rubric()
    )
    return result, github


def event_for(
    item: Student,
    when: datetime = SCHEDULED,
    *,
    head: str = HEAD,
    actor: str | None = None,
    ref: str = "refs/heads/main",
) -> PushRecord:
    return PushRecord(
        "event-1",
        actor or item.github_id,
        when,
        ref,
        head,
        "b" * 40,
    )


def events(*pushes: PushRecord, covered: bool | None = True, limit: bool = False):
    return RepositoryEventsResult(
        raw_events=(),
        push_events=tuple(pushes),
        malformed_push_events=(),
        coverage=EventCoverage(
            fetched_at=GRADED,
            pages_fetched=3 if limit else 1,
            events_fetched=300 if limit else len(pushes),
            oldest_event_at=min((push.created_at for push in pushes), default=None),
            newest_event_at=max((push.created_at for push in pushes), default=None),
            reached_documented_limit=limit,
            latency_window_complete=True,
            assignment_window_covered=covered,
        ),
        page_rate_limits=(),
    )


@dataclass
class Scenario:
    events: RepositoryEventsResult
    professor: CollaboratorStatus = CollaboratorStatus.ACTIVE
    assistant: CollaboratorStatus = CollaboratorStatus.ACTIVE
    readme_text: str | None = None
    readme_missing: bool = False
    repository_error: GitHubErrorCode | None = None
    readme_error: GitHubErrorCode | None = None
    default_branch: str = "main"
    commits: CommitHistoryResult = CommitHistoryResult((), True)
    readmes_by_sha: dict[str, str | None] | None = None
    commits_error: GitHubErrorCode | None = None
    paths_by_sha: dict[str, set[str]] | None = None
    paths_error: GitHubErrorCode | None = None


class FakeGitHub:
    def __init__(self, scenarios: dict[str, Scenario]):
        self.scenarios = scenarios
        self.calls: list[tuple[str, str, str | None]] = []

    def get_repository(self, repository: str) -> RepositoryMetadata:
        self.calls.append(("repository", repository, None))
        scenario = self.scenarios[repository]
        if scenario.repository_error:
            raise GitHubApiError(scenario.repository_error, "repository")
        return RepositoryMetadata(
            100,
            repository,
            True,
            "private",
            scenario.default_branch,
            {"pull": True, "push": True},
        )

    def list_repository_events(self, repository: str) -> RepositoryEventsResult:
        self.calls.append(("events", repository, None))
        return self.scenarios[repository].events

    def list_repository_commits(
        self, repository: str, branch: str, deadline: datetime
    ) -> CommitHistoryResult:
        self.calls.append(("commits", repository, branch))
        if self.scenarios[repository].commits_error:
            raise GitHubApiError(self.scenarios[repository].commits_error, "commits")
        return self.scenarios[repository].commits

    def check_collaborator(
        self,
        repository: str,
        username: str,
        *,
        repository_accessible: bool,
        caller_has_push: bool | None,
    ) -> CollaboratorCheckResult:
        self.calls.append(("collaborator", repository, username))
        scenario = self.scenarios[repository]
        status = (
            scenario.professor if username == "example-professor" else scenario.assistant
        )
        error_code = GitHubErrorCode.API_ERROR if status is CollaboratorStatus.ERROR else None
        return CollaboratorCheckResult(status, GRADED, error_code=error_code)

    def get_readme_at_sha(self, repository: str, sha: str) -> ReadmeAtSha:
        self.calls.append(("readme", repository, sha))
        scenario = self.scenarios[repository]
        if scenario.readme_error:
            raise GitHubApiError(scenario.readme_error, "README")
        if scenario.readmes_by_sha is not None:
            text = scenario.readmes_by_sha.get(sha)
            if text is None:
                return ReadmeAtSha(False, sha)
            return ReadmeAtSha(True, sha, "README.md", "c" * 40, text.encode(), text)
        if scenario.readme_missing:
            return ReadmeAtSha(False, sha)
        text = scenario.readme_text or ""
        return ReadmeAtSha(True, sha, "README.md", "c" * 40, text.encode(), text)

    def get_paths_at_sha(
        self, repository: str, sha: str, paths: tuple[str, ...]
    ) -> RepositoryPathsAtSha:
        self.calls.append(("paths", repository, sha))
        scenario = self.scenarios[repository]
        if scenario.paths_error:
            raise GitHubApiError(scenario.paths_error, "paths")
        existing = (
            scenario.paths_by_sha.get(sha, set())
            if scenario.paths_by_sha is not None
            else (set() if scenario.readme_missing else set(paths))
        )
        return RepositoryPathsAtSha(
            sha,
            tuple(RepositoryPathAtSha(path, path in existing) for path in paths),
        )


def run(item: Student, scenario: Scenario, *, graded_at: datetime = GRADED):
    github = FakeGitHub({item.repository: scenario})
    result = GradingOrchestrator(github, course(), now=lambda: graded_at).grade_student(
        item, rubric()
    )
    return result, github


def complete_scenario(item: Student, *, when: datetime = SCHEDULED) -> Scenario:
    return Scenario(
        events(event_for(item, when)),
        readme_text=f"{item.student_id}\n{item.name}",
    )


def test_on_time_complete_submission_receives_one() -> None:
    result, _ = run(student(), complete_scenario(student()))
    assert (result.submission_status, result.grading_status, result.score) == (
        SubmissionStatus.ON_TIME,
        GradingStatus.PASS,
        1.0,
    )


def test_extended_complete_submission_receives_one() -> None:
    item = student()
    result, _ = run(item, complete_scenario(item, when=EFFECTIVE))
    assert result.submission_status is SubmissionStatus.EXTENDED_ON_TIME
    assert result.score == 1.0


@pytest.mark.parametrize(
    "readme",
    ["Example Student 1", "EXAMPLE001", "README without identity"],
)
def test_incomplete_readme_identity_receives_half(readme: str) -> None:
    item = student()
    result, _ = run(item, Scenario(events(event_for(item)), readme_text=readme))
    assert result.readme_status is ReadmeStatus.INCOMPLETE
    assert result.score == 0.5


@pytest.mark.parametrize("role", ["professor", "assistant"])
def test_reliably_missing_collaborator_receives_zero(role: str) -> None:
    item = student()
    scenario = complete_scenario(item)
    setattr(scenario, role, CollaboratorStatus.MISSING)
    result, github = run(item, scenario)
    assert result.score == 0.0
    assert not any(call[0] == "readme" for call in github.calls)


def test_missing_root_readme_receives_zero() -> None:
    item = student()
    result, _ = run(item, Scenario(events(event_for(item)), readme_missing=True))
    assert (result.readme_status, result.score) == (ReadmeStatus.MISSING, 0.0)


def test_week1_readme_identity_is_irrelevant_and_never_partial() -> None:
    item = student()
    result, github = run_week1(item, Scenario(events(event_for(item, EFFECTIVE)), readme_text="plain README"))
    assert result.score == 1.0
    assert result.grading_status is GradingStatus.PASS
    assert result.readme_status is ReadmeStatus.COMPLETE
    assert [call[2] for call in github.calls if call[0] == "collaborator"] == [
        "example-professor",
        "example-assistant",
    ]


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/main", "refs/heads/master", "refs/heads/week01-submission"],
)
def test_week1_accepts_any_normal_branch_push(ref: str) -> None:
    item = student()
    selected_sha = "d" * 40
    result, github = run_week1(
        item,
        Scenario(
            events(event_for(item, head=selected_sha, ref=ref)),
            readme_text="README",
            default_branch="main",
        ),
    )
    assert result.submission_status is SubmissionStatus.ON_TIME
    assert result.score == 1.0
    assert result.submission_push_ref == ref
    assert result.submission_push_head_sha == selected_sha
    assert result.submission_evidence_source is SubmissionEvidenceSource.PUSH_EVENT_CONFIRMED
    assert ("paths", item.repository, selected_sha) in github.calls


def test_week1_tag_push_does_not_qualify() -> None:
    item = student()
    result, github = run_week1(
        item,
        Scenario(events(event_for(item, ref="refs/tags/week01")), readme_text="README"),
    )
    assert result.submission_status is SubmissionStatus.NOT_SUBMITTED
    assert result.score == 0.0
    assert not any(call[0] in {"collaborator", "readme"} for call in github.calls)


def test_week1_commit_history_fallback_confirms_readme_without_push_event() -> None:
    item = student()
    sha = "f" * 40
    commit = CommitRecord(sha, EFFECTIVE + timedelta(days=1), EFFECTIVE, "main")
    scenario = Scenario(
        events(),
        commits=CommitHistoryResult((commit,), True),
        readmes_by_sha={sha: "README"},
    )
    result, github = run_week1(item, scenario)
    assert result.score == 1.0
    assert result.submission_evidence_source is SubmissionEvidenceSource.COMMIT_HISTORY_CONFIRMED
    assert result.selected_submission_sha == sha
    assert ("paths", item.repository, sha) in github.calls


def test_week1_create_event_is_only_corroboration_for_commit_fallback() -> None:
    item = student()
    sha = "f" * 40
    repository_events = events()
    repository_events = replace(
        repository_events,
        raw_events=({"type": "CreateEvent", "created_at": "2026-09-03T00:00:01Z"},),
    )
    result, _ = run_week1(
        item,
        Scenario(
            repository_events,
            commits=CommitHistoryResult(
                (CommitRecord(sha, None, EFFECTIVE, "main"),), True
            ),
            readmes_by_sha={sha: "README"},
        ),
    )
    assert result.score == 1.0
    assert result.submission_evidence_source is SubmissionEvidenceSource.COMMIT_HISTORY_CONFIRMED


def test_week1_create_event_alone_does_not_prove_readme() -> None:
    item = student()
    repository_events = replace(
        events(),
        raw_events=({"type": "CreateEvent", "created_at": "2026-09-03T00:00:01Z"},),
    )
    result, _ = run_week1(
        item, Scenario(repository_events, commits=CommitHistoryResult((), False))
    )
    assert result.score is None
    assert result.submission_status is SubmissionStatus.UNVERIFIABLE


def test_future_push_only_rubric_does_not_call_commit_history() -> None:
    item = student()
    result, github = run(item, Scenario(events()))
    assert result.submission_status is SubmissionStatus.NOT_SUBMITTED
    assert not any(call[0] == "commits" for call in github.calls)


def test_week1_commit_fallback_uses_committer_date_boundaries() -> None:
    item = student()
    at_deadline = CommitRecord("d" * 40, EFFECTIVE - timedelta(days=1), EFFECTIVE, "main")
    after = CommitRecord(
        "e" * 40,
        EFFECTIVE - timedelta(days=1),
        EFFECTIVE + timedelta(seconds=1),
        "main",
    )
    result, _ = run_week1(
        item,
        Scenario(
            events(),
            commits=CommitHistoryResult((after, at_deadline), True),
            readmes_by_sha={at_deadline.sha: "README", after.sha: "README"},
        ),
    )
    assert result.score == 1.0
    assert result.selected_submission_sha == at_deadline.sha


def test_week1_commit_fallback_selects_latest_predeadline_readme() -> None:
    item = student()
    older = CommitRecord("c" * 40, None, EFFECTIVE - timedelta(days=2), "main")
    latest_without = CommitRecord("d" * 40, None, EFFECTIVE - timedelta(days=1), "main")
    latest_with = CommitRecord("e" * 40, None, EFFECTIVE - timedelta(hours=1), "main")
    result, _ = run_week1(
        item,
        Scenario(
            events(),
            commits=CommitHistoryResult((older, latest_without, latest_with), True),
            readmes_by_sha={older.sha: "README", latest_with.sha: "README"},
        ),
    )
    assert result.selected_submission_sha == latest_with.sha


def test_week1_complete_commit_history_without_readme_is_zero() -> None:
    item = student()
    commit = CommitRecord("c" * 40, None, EFFECTIVE, "main")
    result, _ = run_week1(
        item,
        Scenario(
            events(),
            commits=CommitHistoryResult((commit,), True),
            paths_by_sha={},
        ),
    )
    assert result.readme_status is ReadmeStatus.MISSING
    assert result.score == 0.0


def test_week1_accessible_empty_repository_is_reliable_zero() -> None:
    item = student()
    result, github = run_week1(
        item, Scenario(events(), commits=CommitHistoryResult((), True))
    )
    assert result.submission_status is SubmissionStatus.NOT_SUBMITTED
    assert result.score == 0.0
    assert result.error_code is None
    assert result.manual_review_reason == "EMPTY_REPOSITORY"
    assert [call[0] for call in github.calls[:3]] == ["repository", "events", "commits"]


def test_week1_only_postdeadline_commits_are_late_zero() -> None:
    item = student()
    late = CommitRecord(
        "e" * 40, None, EFFECTIVE + timedelta(seconds=1), "main"
    )
    result, _ = run_week1(
        item,
        Scenario(
            events(),
            commits=CommitHistoryResult((late,), True),
            readmes_by_sha={late.sha: "README"},
        ),
    )
    assert result.submission_status is SubmissionStatus.LATE
    assert result.score == 0.0
    assert result.manual_review_reason == "NO_TIMELY_SUBMISSION"


def test_week1_commit_api_failure_is_error_null() -> None:
    item = student()
    result, _ = run_week1(
        item,
        Scenario(events(), commits_error=GitHubErrorCode.API_ERROR),
    )
    assert result.submission_status is SubmissionStatus.ERROR
    assert result.grading_status is GradingStatus.ERROR
    assert result.score is None
    assert result.error_code == "API_ERROR"


@pytest.mark.parametrize(
    "existing",
    [
        {"README.md", "week01/README.md"},
        {"README.md", "week01-01/README.md"},
        {"README.md", "week01/README.md", "week01-01/README.md"},
    ],
)
def test_week1_required_path_groups_accept_either_project_readme(
    existing: set[str],
) -> None:
    item = student()
    result, _ = run_week1(
        item,
        Scenario(events(event_for(item)), paths_by_sha={HEAD: existing}),
    )
    assert result.score == 1.0
    assert all(check.status.value == "SATISFIED" for check in result.required_path_checks)


def test_generic_path_groups_do_not_depend_on_legacy_readme_flag() -> None:
    item = student()
    github = FakeGitHub(
        {
            item.repository: Scenario(
                events(event_for(item)),
                paths_by_sha={HEAD: {"README.md", "week01/README.md"}},
            )
        }
    )
    configured = week1_rubric()
    configured = replace(
        configured,
        grading=replace(configured.grading, readme_required=False),
    )
    result = GradingOrchestrator(github, course(), now=lambda: GRADED).grade_student(
        item, configured
    )
    assert result.score == 1.0
    assert ("paths", item.repository, HEAD) in github.calls


@pytest.mark.parametrize(
    ("existing", "reason"),
    [
        ({"README.md"}, "PROJECT_README_MISSING"),
        ({"week01/README.md"}, "ROOT_README_MISSING"),
        (set(), "ROOT_README_MISSING"),
        ({"docs/README.md", "Week01/README.md"}, "ROOT_README_MISSING"),
    ],
)
def test_week1_missing_required_path_group_is_reliable_zero(
    existing: set[str], reason: str
) -> None:
    item = student()
    result, _ = run_week1(
        item,
        Scenario(events(event_for(item)), paths_by_sha={HEAD: existing}),
    )
    assert result.score == 0.0
    assert result.required_path_failure_reason == reason
    assert result.manual_review_reason == reason


def test_week1_push_uses_selected_historical_sha_not_current_state() -> None:
    item = student()
    result, github = run_week1(
        item,
        Scenario(
            events(event_for(item, head=HEAD)),
            paths_by_sha={HEAD: {"README.md"}},
        ),
    )
    assert result.score == 0.0
    assert result.required_path_failure_reason == "PROJECT_README_MISSING"
    assert ("paths", item.repository, HEAD) in github.calls


def test_week1_commit_fallback_selects_latest_snapshot_satisfying_all_groups() -> None:
    item = student()
    older = CommitRecord("c" * 40, None, EFFECTIVE - timedelta(days=2), "main")
    satisfied = CommitRecord("d" * 40, None, EFFECTIVE - timedelta(days=1), "main")
    newer_deleted = CommitRecord("e" * 40, None, EFFECTIVE, "main")
    result, _ = run_week1(
        item,
        Scenario(
            events(),
            commits=CommitHistoryResult((newer_deleted, satisfied, older), True),
            paths_by_sha={
                older.sha: {"README.md", "week01-01/README.md"},
                satisfied.sha: {"README.md", "week01/README.md"},
                newer_deleted.sha: {"README.md"},
            },
        ),
    )
    assert result.score == 1.0
    assert result.selected_submission_sha == satisfied.sha
    assert result.submission_evidence_source is SubmissionEvidenceSource.COMMIT_HISTORY_CONFIRMED


@pytest.mark.parametrize(
    "predeadline_paths",
    [
        {"README.md"},
        {"week01/README.md"},
    ],
)
def test_week1_postdeadline_file_addition_does_not_retroactively_qualify(
    predeadline_paths: set[str],
) -> None:
    item = student()
    before = CommitRecord("c" * 40, None, EFFECTIVE, "before cutoff")
    after = CommitRecord(
        "d" * 40, None, EFFECTIVE + timedelta(seconds=1), "after cutoff"
    )
    result, _ = run_week1(
        item,
        Scenario(
            events(),
            commits=CommitHistoryResult((after, before), True),
            paths_by_sha={
                before.sha: predeadline_paths,
                after.sha: {"README.md", "week01/README.md"},
            },
        ),
    )
    assert result.score == 0.0
    assert result.selected_submission_sha == before.sha


def test_week1_incomplete_commit_history_is_null_not_not_submitted() -> None:
    item = student()
    result, _ = run_week1(
        item, Scenario(events(), commits=CommitHistoryResult((), False))
    )
    assert result.submission_status is SubmissionStatus.UNVERIFIABLE
    assert result.score is None


def test_future_rubric_still_enforces_explicit_branch() -> None:
    item = student()
    scenario = Scenario(
        events(event_for(item, ref="refs/heads/develop")),
        readme_text=f"{item.student_id}\n{item.name}",
        default_branch="develop",
    )
    github = FakeGitHub({item.repository: scenario})
    result = GradingOrchestrator(github, course(), now=lambda: GRADED).grade_student(
        item, rubric(branch="main")
    )
    assert result.submission_status is SubmissionStatus.NOT_SUBMITTED
    assert result.score == 0.0


def test_week1_actor_and_deadline_filters_are_unchanged() -> None:
    item = student()
    wrong_actor = event_for(item, actor="another-user", ref="refs/heads/master")
    after_deadline = event_for(
        item,
        EFFECTIVE + timedelta(seconds=1),
        ref="refs/heads/another-branch",
    )
    result, _ = run_week1(item, Scenario(events(wrong_actor, after_deadline)))
    assert result.submission_status is SubmissionStatus.NOT_SUBMITTED
    assert result.score == 0.0


@pytest.mark.parametrize(
    ("section", "when"),
    [
        ("01", datetime(2026, 8, 31, tzinfo=UTC)),
        ("02", datetime(2026, 9, 1, tzinfo=UTC)),
        ("02", datetime(2026, 9, 2, tzinfo=UTC)),
    ],
)
def test_week1_deadline_only_policy_accepts_early_pushes(section: str, when: datetime) -> None:
    item = replace(student(), section=section)
    result, _ = run_week1(item, Scenario(events(event_for(item, when)), readme_text="README"))
    assert result.submission_status is SubmissionStatus.ON_TIME
    assert result.score == 1.0


def test_week1_selects_latest_predeadline_sha_and_ignores_postdeadline_push() -> None:
    item = student()
    older = event_for(item, datetime(2026, 8, 31, tzinfo=UTC), head="c" * 40)
    timely = PushRecord("event-2", item.github_id, datetime(2026, 9, 2, tzinfo=UTC), "refs/heads/main", "d" * 40, "c" * 40)
    late = PushRecord("event-3", item.github_id, EFFECTIVE + timedelta(seconds=1), "refs/heads/main", "e" * 40, "d" * 40)
    result, github = run_week1(item, Scenario(events(older, timely, late), readme_text="README"))
    assert result.submission_push_head_sha == "d" * 40
    assert ("paths", item.repository, "d" * 40) in github.calls


def test_week1_both_collaborators_are_required() -> None:
    item = student()
    missing_assistant = Scenario(events(event_for(item)), assistant=CollaboratorStatus.MISSING)
    result, _ = run_week1(item, missing_assistant)
    assert result.score == 0.0
    missing_professor = Scenario(events(event_for(item)), professor=CollaboratorStatus.MISSING, readme_text="README")
    result, github = run_week1(item, missing_professor)
    assert result.score == 0.0
    assert any(call[2] == "example-professor" for call in github.calls)


def test_week1_both_missing_collaborators_are_reliable_zero() -> None:
    item = student()
    result, _ = run_week1(
        item,
        Scenario(
            events(event_for(item)),
            professor=CollaboratorStatus.MISSING,
            assistant=CollaboratorStatus.MISSING,
        ),
    )
    assert result.score == 0.0


@pytest.mark.parametrize(
    ("role", "status"),
    [
        ("professor", CollaboratorStatus.UNKNOWN),
        ("assistant", CollaboratorStatus.ERROR),
    ],
)
def test_week1_required_collaborator_uncertainty_is_null(
    role: str, status: CollaboratorStatus
) -> None:
    item = student()
    scenario = Scenario(events(event_for(item)))
    setattr(scenario, role, status)
    result, _ = run_week1(item, scenario)
    assert result.score is None


def test_week1_collaborators_are_current_state_only() -> None:
    item = student()
    result, _ = run_week1(item, Scenario(events(event_for(item))))
    assert result.score == 1.0
    # Collaborator evidence has no historical timestamp input by design.
    assert result.professor_collaborator_checked_at == GRADED
    assert result.assistant_collaborator_checked_at == GRADED


def test_week1_no_timely_push_is_zero_after_effective_settle_without_late_wait() -> None:
    item = student()
    no_push, _ = run_week1(item, Scenario(events()))
    late_only, github = run_week1(
        item, Scenario(events(event_for(item, EFFECTIVE + timedelta(seconds=1))))
    )
    assert (no_push.submission_status, no_push.score) == (SubmissionStatus.NOT_SUBMITTED, 0.0)
    assert (late_only.submission_status, late_only.score) == (SubmissionStatus.NOT_SUBMITTED, 0.0)
    assert not any(call[0] in {"collaborator", "readme"} for call in github.calls)


def test_week1_assistant_uncertainty_and_unresolvable_sha_remain_null() -> None:
    item = student()
    unknown, _ = run_week1(item, Scenario(events(event_for(item)), assistant=CollaboratorStatus.UNKNOWN))
    unresolved, _ = run_week1(item, Scenario(events(event_for(item)), paths_error=GitHubErrorCode.UNRESOLVABLE_REF))
    assert unknown.score is None and unknown.grading_status is GradingStatus.MANUAL_REVIEW
    assert unresolved.score is None and unresolved.readme_status is ReadmeStatus.UNVERIFIABLE


def test_week1_missing_readme_is_zero_but_incomplete_events_are_null() -> None:
    item = student()
    missing, _ = run_week1(item, Scenario(events(event_for(item)), readme_missing=True))
    incomplete, _ = run_week1(
        item,
        Scenario(events(covered=False), commits=CommitHistoryResult((), False)),
    )
    assert missing.readme_status is ReadmeStatus.MISSING and missing.score == 0.0
    assert incomplete.submission_status is SubmissionStatus.UNVERIFIABLE
    assert incomplete.score is None


def test_late_submission_receives_zero_without_downstream_calls() -> None:
    item = student()
    result, github = run(
        item,
        Scenario(events(event_for(item, EFFECTIVE + timedelta(seconds=1)))),
    )
    assert (result.submission_status, result.score) == (SubmissionStatus.LATE, 0.0)
    assert [call[0] for call in github.calls] == ["repository", "events"]


def test_reliable_absence_is_not_submitted_zero() -> None:
    item = student()
    result, _ = run(item, Scenario(events()))
    assert (result.submission_status, result.score) == (
        SubmissionStatus.NOT_SUBMITTED,
        0.0,
    )


def test_incomplete_or_truncated_events_are_null() -> None:
    item = student()
    incomplete, _ = run(item, Scenario(events(covered=False)))
    truncated, _ = run(item, Scenario(events(covered=None, limit=True)))
    assert incomplete.score is None and truncated.score is None
    assert incomplete.submission_status is SubmissionStatus.UNVERIFIABLE
    assert truncated.submission_status is SubmissionStatus.UNVERIFIABLE


def test_grading_before_settle_time_makes_no_api_call() -> None:
    item = student()
    github = FakeGitHub({item.repository: complete_scenario(item)})
    result = GradingOrchestrator(
        github,
        course(),
        now=lambda: EFFECTIVE + timedelta(hours=5, minutes=59),
    ).grade_student(item, rubric())
    assert result.submission_status is SubmissionStatus.EVIDENCE_NOT_SETTLED
    assert result.score is None
    assert github.calls == []


@pytest.mark.parametrize(
    ("status", "grading"),
    [
        (CollaboratorStatus.UNKNOWN, GradingStatus.MANUAL_REVIEW),
        (CollaboratorStatus.ERROR, GradingStatus.ERROR),
    ],
)
def test_uncertain_collaborator_is_never_zero(status, grading) -> None:
    item = student()
    scenario = complete_scenario(item)
    scenario.professor = status
    result, _ = run(item, scenario)
    assert result.grading_status is grading
    assert result.score is None
    if status is CollaboratorStatus.ERROR:
        assert result.error_code == GitHubErrorCode.API_ERROR.value


@pytest.mark.parametrize(
    ("code", "readme_status", "grading"),
    [
        (GitHubErrorCode.UNRESOLVABLE_REF, ReadmeStatus.UNVERIFIABLE, GradingStatus.MANUAL_REVIEW),
        (GitHubErrorCode.API_ERROR, ReadmeStatus.ERROR, GradingStatus.ERROR),
    ],
)
def test_readme_technical_failure_is_never_missing_or_zero(code, readme_status, grading) -> None:
    item = student()
    scenario = complete_scenario(item)
    scenario.readme_error = code
    result, _ = run(item, scenario)
    assert result.readme_status is readme_status
    assert result.grading_status is grading
    assert result.score is None


def test_selected_sha_is_passed_unchanged_and_preserved_for_future_c_grading() -> None:
    item = student()
    selected_sha = "d" * 40
    scenario = Scenario(
        events(event_for(item, head=selected_sha)),
        readme_text=f"{item.student_id}\n{item.name}",
    )
    result, github = run(item, scenario)
    assert ("readme", item.repository, selected_sha) in github.calls
    assert result.submission_push_head_sha == selected_sha
    assert result.selected_push is not None
    assert result.selected_push.head_sha == selected_sha


def test_ambiguous_submission_is_manual_review_without_readme() -> None:
    item = student()
    first = event_for(item, head="a" * 40)
    second = PushRecord(
        "event-2", item.github_id, first.created_at, first.ref, "d" * 40, first.before_sha
    )
    result, github = run(item, Scenario(events(first, second)))
    assert result.submission_status is SubmissionStatus.AMBIGUOUS_SUBMISSION
    assert result.score is None
    assert not any(call[0] == "readme" for call in github.calls)


def test_repository_api_failure_stops_downstream_calls() -> None:
    item = student()
    result, github = run(
        item,
        Scenario(events(), repository_error=GitHubErrorCode.PERMISSION_ERROR),
    )
    assert result.score is None
    assert result.error_code == GitHubErrorCode.PERMISSION_ERROR.value
    assert [call[0] for call in github.calls] == ["repository"]


def test_final_week_missing_late_end_is_manual_review_without_api_calls() -> None:
    item = student()
    github = FakeGitHub({item.repository: complete_scenario(item)})
    result = GradingOrchestrator(github, course(), now=lambda: GRADED).grade_student(
        item, rubric(late_end=None)
    )
    assert result.submission_status is SubmissionStatus.CONFIGURATION_ERROR
    assert result.score is None
    assert github.calls == []


def test_section_grading_preserves_all_students_after_one_failure() -> None:
    students = [student(index) for index in range(1, 5)]
    scenarios = {
        students[0].repository: complete_scenario(students[0]),
        students[1].repository: Scenario(
            events(event_for(students[1])), readme_text=students[1].student_id
        ),
        students[2].repository: Scenario(
            events(event_for(students[2], EFFECTIVE + timedelta(seconds=1)))
        ),
        students[3].repository: Scenario(
            events(), repository_error=GitHubErrorCode.NETWORK_ERROR
        ),
    }
    results = GradingOrchestrator(
        FakeGitHub(scenarios), course(), now=lambda: GRADED
    ).grade_section_week(students, "01", rubric())
    assert len(results) == 4
    assert [result.score for result in results] == [1.0, 0.5, 0.0, None]
    assert results[-1].grading_status is GradingStatus.ERROR


def test_missing_registration_is_null_without_github_call_and_section_continues() -> None:
    missing = Student("01", "EXAMPLE000", "Unregistered Student", "", "")
    registered = student(1)
    github = FakeGitHub({registered.repository: complete_scenario(registered)})
    results = GradingOrchestrator(github, course(), now=lambda: GRADED).grade_section_week(
        [missing, registered], "01", rubric()
    )
    assert len(results) == 2
    assert results[0].submission_status is SubmissionStatus.MISSING_REPOSITORY_INFO
    assert results[0].grading_status is GradingStatus.MANUAL_REVIEW
    assert results[0].score is None
    assert results[0].error_code == "MISSING_REPOSITORY_INFO"
    assert all(call[1] != "" for call in github.calls)
    assert results[1].score == 1.0


def test_unknown_section_is_configuration_result_not_exception() -> None:
    item = Student("99", "EXAMPLE999", "Example Student", "example-student", "owner/repo")
    result = GradingOrchestrator(FakeGitHub({}), course(), now=lambda: GRADED).grade_student(
        item, rubric()
    )
    assert result.submission_status is SubmissionStatus.CONFIGURATION_ERROR
    assert result.score is None


def test_unknown_week_is_configuration_result_not_exception() -> None:
    item = student()
    invalid_week = WeeklyRubric(
        15,
        "Out of range",
        1.0,
        "main",
        True,
        {"01": SectionDeadline(START, SCHEDULED, EFFECTIVE, LATE_END)},
        GradingRules(),
        ScoreRules(1.0, 0.5, 0.0),
    )
    result = GradingOrchestrator(FakeGitHub({}), course(), now=lambda: GRADED).grade_student(
        item, invalid_week
    )
    assert result.submission_status is SubmissionStatus.CONFIGURATION_ERROR
    assert result.score is None
