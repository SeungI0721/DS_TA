"""submission selection과 Events coverage의 순수 경계 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from github_lab_grader.models import (
    EventCoverage,
    GradingRules,
    LateWindowSource,
    PushRecord,
    RepositoryEventsResult,
    ResolvedSectionDeadline,
    ScoreRules,
    SectionDeadline,
    Student,
    SubmissionStatus,
    WeeklyRubric,
)
from github_lab_grader.submission_checker import (
    resolve_section_deadline,
    select_submission,
)


START = datetime(2026, 9, 1, tzinfo=UTC)
SCHEDULED = datetime(2026, 9, 2, tzinfo=UTC)
EFFECTIVE = datetime(2026, 9, 3, tzinfo=UTC)
LATE_END = datetime(2026, 9, 8, tzinfo=UTC)
GRADED = LATE_END + timedelta(hours=7)
STUDENT = Student("01", "EXAMPLE001", "Example Student", "student-example", "owner/repo")
TIMING = ResolvedSectionDeadline(
    START, SCHEDULED, EFFECTIVE, LATE_END, LateWindowSource.EXPLICIT
)


def push(
    when: datetime,
    *,
    event_id: str = "event-1",
    head: str = "a" * 40,
    actor: str = "student-example",
    ref: str = "refs/heads/main",
) -> PushRecord:
    return PushRecord(event_id, actor, when, ref, head, "b" * 40)


def evidence(
    *pushes: PushRecord,
    covered: bool | None = True,
    limit: bool = False,
    malformed: tuple[str, ...] = (),
):
    coverage = EventCoverage(
        fetched_at=GRADED,
        pages_fetched=3 if limit else 1,
        events_fetched=300 if limit else len(pushes),
        oldest_event_at=min((item.created_at for item in pushes), default=None),
        newest_event_at=max((item.created_at for item in pushes), default=None),
        reached_documented_limit=limit,
        latency_window_complete=True,
        assignment_window_covered=covered,
    )
    return RepositoryEventsResult((), tuple(pushes), malformed, coverage, ())


def select(*pushes: PushRecord, covered: bool | None = True, limit: bool = False):
    return select_submission(
        evidence(*pushes, covered=covered, limit=limit),
        STUDENT,
        "main",
        TIMING,
        GRADED,
        settle_delay=timedelta(hours=6),
        history_max_age=timedelta(days=30),
    )


def test_push_exactly_at_scheduled_deadline_is_on_time() -> None:
    assert select(push(SCHEDULED)).status is SubmissionStatus.ON_TIME


def test_push_after_scheduled_before_effective_is_extended_on_time() -> None:
    result = select(push(SCHEDULED + timedelta(seconds=1)))
    assert result.status is SubmissionStatus.EXTENDED_ON_TIME


def test_push_exactly_at_effective_deadline_is_valid() -> None:
    assert select(push(EFFECTIVE)).status is SubmissionStatus.EXTENDED_ON_TIME


def test_push_after_effective_before_late_end_is_late() -> None:
    assert select(push(EFFECTIVE + timedelta(seconds=1))).status is SubmissionStatus.LATE


def test_events_after_late_window_are_ignored() -> None:
    assert select(push(LATE_END + timedelta(seconds=1))).status is SubmissionStatus.NOT_SUBMITTED


def test_previous_week_push_does_not_count() -> None:
    assert select(push(START - timedelta(seconds=1))).status is SubmissionStatus.NOT_SUBMITTED


def test_latest_eligible_push_is_selected() -> None:
    earlier = push(SCHEDULED - timedelta(hours=1), event_id="1", head="a" * 40)
    later = push(EFFECTIVE, event_id="2", head="c" * 40)
    result = select(earlier, later)
    assert result.selected_push == later


def test_conflicting_same_second_pushes_require_manual_review() -> None:
    result = select(
        push(EFFECTIVE, event_id="1", head="a" * 40),
        push(EFFECTIVE, event_id="2", head="c" * 40),
    )
    assert result.status is SubmissionStatus.AMBIGUOUS_SUBMISSION


def test_duplicate_same_second_same_sha_is_safe() -> None:
    result = select(push(EFFECTIVE, event_id="2"), push(EFFECTIVE, event_id="1"))
    assert result.status is SubmissionStatus.EXTENDED_ON_TIME
    assert result.selected_push is not None
    assert result.selected_push.event_id == "1"


def test_missing_late_end_derives_from_next_week_start_minus_one_second() -> None:
    current = rubric(1, SectionDeadline(START, SCHEDULED, EFFECTIVE, None))
    next_start = datetime(2026, 9, 10, tzinfo=UTC)
    following = rubric(
        2,
        SectionDeadline(
            next_start,
            next_start + timedelta(days=1),
            next_start + timedelta(days=1),
            next_start + timedelta(days=2),
        ),
    )
    resolved = resolve_section_deadline(current, "01", following)
    assert resolved.late_window_end == next_start - timedelta(seconds=1)
    assert resolved.late_window_source is LateWindowSource.NEXT_WEEK_DERIVED


def test_final_week_without_late_end_uses_conservative_status() -> None:
    current = rubric(14, SectionDeadline(START, SCHEDULED, EFFECTIVE, None))
    resolved = resolve_section_deadline(current, "01")
    result = select_submission(
        evidence(),
        STUDENT,
        "main",
        resolved,
        GRADED,
        settle_delay=timedelta(hours=6),
        history_max_age=timedelta(days=30),
    )
    assert result.status is SubmissionStatus.CONFIGURATION_ERROR


def test_different_sections_resolve_independent_deadlines() -> None:
    second = SectionDeadline(
        START + timedelta(days=1),
        SCHEDULED + timedelta(days=1),
        EFFECTIVE + timedelta(days=1),
        LATE_END + timedelta(days=1),
    )
    item = rubric(1, SectionDeadline(START, SCHEDULED, EFFECTIVE, LATE_END), second)
    assert resolve_section_deadline(item, "01").scheduled_deadline == SCHEDULED
    assert resolve_section_deadline(item, "02").scheduled_deadline == SCHEDULED + timedelta(days=1)


def test_insufficient_event_history_is_unverifiable() -> None:
    assert select(covered=False).status is SubmissionStatus.UNVERIFIABLE


def test_300_event_limit_without_window_coverage_is_unverifiable() -> None:
    assert select(covered=None, limit=True).status is SubmissionStatus.UNVERIFIABLE


def test_malformed_push_evidence_is_unverifiable_even_with_valid_candidate() -> None:
    result = select_submission(
        evidence(push(SCHEDULED), malformed=("broken event",)),
        STUDENT,
        "main",
        TIMING,
        GRADED,
        settle_delay=timedelta(hours=6),
        history_max_age=timedelta(days=30),
    )
    assert result.status is SubmissionStatus.UNVERIFIABLE


def test_actor_matching_is_case_insensitive() -> None:
    assert select(push(SCHEDULED, actor="STUDENT-EXAMPLE")).status is SubmissionStatus.ON_TIME


def test_other_actor_wrong_branch_and_tag_are_ignored() -> None:
    result = select(
        push(SCHEDULED, actor="other-user"),
        push(SCHEDULED, ref="refs/heads/develop"),
        push(SCHEDULED, ref="refs/tags/main"),
    )
    assert result.status is SubmissionStatus.NOT_SUBMITTED


def test_later_late_push_does_not_replace_accepted_submission() -> None:
    accepted = push(EFFECTIVE, event_id="accepted")
    late = push(EFFECTIVE + timedelta(days=1), event_id="late", head="c" * 40)
    result = select(accepted, late)
    assert result.selected_push == accepted


def test_same_second_late_pushes_with_different_shas_are_ambiguous() -> None:
    when = EFFECTIVE + timedelta(seconds=1)
    result = select(
        push(when, event_id="1", head="a" * 40),
        push(when, event_id="2", head="c" * 40),
    )
    assert result.status is SubmissionStatus.AMBIGUOUS_SUBMISSION


def rubric(
    week: int,
    first: SectionDeadline,
    second: SectionDeadline | None = None,
) -> WeeklyRubric:
    sections = {"01": first}
    if second is not None:
        sections["02"] = second
    return WeeklyRubric(
        week,
        "Example",
        1.0,
        "main",
        True,
        sections,
        GradingRules(),
        ScoreRules(1.0, 0.5, 0.0),
    )
