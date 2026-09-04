"""학생 및 section/week orchestration의 offline integration 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from github_lab_grader.github_client import GitHubApiError
from github_lab_grader.models import (
    CollaboratorCheckResult,
    CollaboratorStatus,
    CourseConfig,
    EventCoverage,
    GitHubErrorCode,
    GradingRules,
    GradingStatus,
    PushRecord,
    ReadmeAtSha,
    ReadmeStatus,
    RepositoryEventsResult,
    RepositoryMetadata,
    ScoreRules,
    SectionDeadline,
    Student,
    SubmissionStatus,
    WeeklyRubric,
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


def event_for(item: Student, when: datetime = SCHEDULED, *, head: str = HEAD) -> PushRecord:
    return PushRecord(
        "event-1",
        item.github_id,
        when,
        "refs/heads/main",
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
        if scenario.readme_missing:
            return ReadmeAtSha(False, sha)
        text = scenario.readme_text or ""
        return ReadmeAtSha(True, sha, "README.md", "c" * 40, text.encode(), text)


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
