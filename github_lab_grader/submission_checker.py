"""주차별 제출 구간, Events coverage, PushEvent 선택을 판정하는 순수 계층."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from .models import (
    EventCoverage,
    LateWindowSource,
    PushRecord,
    PathGroupStatus,
    RepositoryPathsAtSha,
    RequiredPathGroup,
    RequiredPathGroupResult,
    RepositoryEventsResult,
    ResolvedSectionDeadline,
    Student,
    SubmissionDecision,
    SubmissionEvidenceSource,
    SubmissionStatus,
    SubmissionTimestampType,
    WeeklyRubric,
)


def evaluate_required_path_groups(
    groups: tuple[RequiredPathGroup, ...], evidence: RepositoryPathsAtSha
) -> tuple[RequiredPathGroupResult, ...]:
    """동일 SHA의 exact path evidence로 각 필수 ANY group을 판정한다."""

    exists = {item.path for item in evidence.paths if item.exists}
    return tuple(
        RequiredPathGroupResult(
            group.name,
            group.match,
            group.paths,
            next((path for path in group.paths if path in exists), None),
            (
                PathGroupStatus.SATISFIED
                if any(path in exists for path in group.paths)
                else PathGroupStatus.MISSING
            ),
            group.failure_reason,
        )
        for group in groups
    )


def resolve_section_deadline(
    rubric: WeeklyRubric,
    section: str,
    next_rubric: WeeklyRubric | None = None,
) -> ResolvedSectionDeadline:
    """명시된 late end를 우선하고 다음 주 시작 1초 전을 보조 경계로 사용한다."""

    try:
        timing = rubric.sections[section]
    except KeyError as exc:
        raise ValueError(f"unknown section: {section}") from exc
    if timing.late_window_end is not None:
        late_end = timing.late_window_end
        source = LateWindowSource.EXPLICIT
    elif next_rubric is not None and section in next_rubric.sections:
        late_end = next_rubric.sections[section].submission_window_start - timedelta(seconds=1)
        source = LateWindowSource.NEXT_WEEK_DERIVED
        if late_end <= timing.effective_deadline:
            raise ValueError("derived late_window_end must be after effective_deadline")
    else:
        late_end = None
        source = LateWindowSource.UNAVAILABLE
    return ResolvedSectionDeadline(
        submission_window_start=timing.submission_window_start,
        scheduled_deadline=timing.scheduled_deadline,
        effective_deadline=timing.effective_deadline,
        late_window_end=late_end,
        late_window_source=source,
        deadline_note=timing.deadline_note,
    )


def resolve_submission_branch(configured_branch: str, default_branch: str) -> str:
    """`default`만 현재 repository default branch로 치환한다."""

    branch = default_branch if configured_branch == "default" else configured_branch
    if not branch or branch.startswith("refs/"):
        raise ValueError("submission branch must be a branch name or 'default'")
    return branch


def valid_student_pushes(
    pushes: Iterable[PushRecord],
    student: Student,
    branch: str,
    timing: ResolvedSectionDeadline,
    *,
    require_actor: bool,
    use_late_window: bool = True,
    enforce_submission_window_start: bool = True,
    enforce_submission_branch: bool = True,
) -> tuple[PushRecord, ...]:
    """actor, branch ref, 주차 범위를 모두 충족하는 push만 보존한다."""

    cutoff = timing.late_window_end if use_late_window else timing.effective_deadline
    if cutoff is None:
        return ()
    expected_ref = f"refs/heads/{branch}"
    return tuple(
        push
        for push in pushes
        if (not require_actor or push.actor.casefold() == student.github_id.casefold())
        and push.ref.startswith("refs/heads/")
        and len(push.ref) > len("refs/heads/")
        and (not enforce_submission_branch or push.ref == expected_ref)
        and (not enforce_submission_window_start or timing.submission_window_start <= push.created_at)
        and push.created_at <= cutoff
    )


def event_history_covers_window(
    coverage: EventCoverage,
    timing: ResolvedSectionDeadline,
    history_max_age: timedelta,
    *,
    enforce_submission_window_start: bool = True,
) -> bool:
    """Events 보존 한계 안에서 필요한 시작 시각까지 조회됐는지 보수적으로 판정한다."""

    if coverage.assignment_window_covered is not None:
        return coverage.assignment_window_covered
    if not enforce_submission_window_start:
        return not coverage.reached_documented_limit
    oldest = coverage.oldest_event_at
    if oldest is not None and oldest <= timing.submission_window_start:
        return True
    if coverage.reached_documented_limit:
        return False
    return coverage.fetched_at - timing.submission_window_start <= history_max_age


def select_submission(
    events: RepositoryEventsResult,
    student: Student,
    branch: str,
    timing: ResolvedSectionDeadline,
    graded_at: datetime,
    *,
    settle_delay: timedelta,
    history_max_age: timedelta,
    require_actor: bool = True,
    use_late_window: bool = True,
    enforce_submission_window_start: bool = True,
    enforce_submission_branch: bool = True,
) -> SubmissionDecision:
    """최신 accepted push를 선택하고 불충분한 부재 증거는 0점으로 바꾸지 않는다."""

    if graded_at.tzinfo is None or graded_at.utcoffset() is None:
        raise ValueError("graded_at must be timezone-aware")
    if use_late_window and timing.late_window_end is None:
        return SubmissionDecision(
            SubmissionStatus.CONFIGURATION_ERROR,
            evidence_complete=False,
            reason="late_window_end cannot be resolved",
        )
    if graded_at < timing.effective_deadline + settle_delay:
        return SubmissionDecision(
            SubmissionStatus.EVIDENCE_NOT_SETTLED,
            evidence_complete=False,
            reason="GitHub Events settle delay has not elapsed",
        )

    candidates = valid_student_pushes(
        events.push_events,
        student,
        branch,
        timing,
        require_actor=require_actor,
        use_late_window=use_late_window,
        enforce_submission_window_start=enforce_submission_window_start,
        enforce_submission_branch=enforce_submission_branch,
    )
    if events.malformed_push_events:
        return SubmissionDecision(
            SubmissionStatus.UNVERIFIABLE,
            evidence_complete=False,
            reason="malformed PushEvent evidence may affect submission selection",
        )
    accepted = tuple(
        push for push in candidates if push.created_at <= timing.effective_deadline
    )
    if accepted:
        latest_time = max(push.created_at for push in accepted)
        latest = tuple(push for push in accepted if push.created_at == latest_time)
        distinct_shas = {push.head_sha for push in latest}
        if len(distinct_shas) > 1:
            return SubmissionDecision(
                SubmissionStatus.AMBIGUOUS_SUBMISSION,
                evidence_complete=False,
                reason="different head SHAs share the latest PushEvent timestamp",
            )
        selected = min(latest, key=lambda push: push.event_id)
        status = (
            SubmissionStatus.ON_TIME
            if selected.created_at <= timing.scheduled_deadline
            else SubmissionStatus.EXTENDED_ON_TIME
        )
        return SubmissionDecision(
            status,
            selected_push=selected,
            evidence_source=SubmissionEvidenceSource.PUSH_EVENT_CONFIRMED,
            selected_sha=selected.head_sha,
            selected_timestamp=selected.created_at,
            timestamp_type=SubmissionTimestampType.PUSH_EVENT_CREATED_AT,
        )

    if not use_late_window:
        if not event_history_covers_window(
            events.coverage,
            timing,
            history_max_age,
            enforce_submission_window_start=enforce_submission_window_start,
        ):
            return SubmissionDecision(
                SubmissionStatus.UNVERIFIABLE,
                evidence_complete=False,
                reason="repository event history does not cover the assignment window",
            )
        return SubmissionDecision(SubmissionStatus.NOT_SUBMITTED)

    # Accepted push가 없을 때에는 late window 전체와 Events coverage가 모두 확정돼야
    # LATE 또는 NOT_SUBMITTED라는 징벌적 결론을 내릴 수 있다.
    if graded_at < timing.late_window_end + settle_delay:
        return SubmissionDecision(
            SubmissionStatus.EVIDENCE_NOT_SETTLED,
            evidence_complete=False,
            reason="late submission window evidence has not settled",
        )
    if not event_history_covers_window(
        events.coverage,
        timing,
        history_max_age,
        enforce_submission_window_start=enforce_submission_window_start,
    ):
        return SubmissionDecision(
            SubmissionStatus.UNVERIFIABLE,
            evidence_complete=False,
            reason="repository event history does not cover the assignment window",
        )
    late = tuple(push for push in candidates if push.created_at > timing.effective_deadline)
    if late:
        latest_time = max(push.created_at for push in late)
        latest = tuple(push for push in late if push.created_at == latest_time)
        if len({push.head_sha for push in latest}) > 1:
            return SubmissionDecision(
                SubmissionStatus.AMBIGUOUS_SUBMISSION,
                evidence_complete=False,
                reason="different late head SHAs share the latest PushEvent timestamp",
            )
        selected = min(latest, key=lambda push: push.event_id)
        return SubmissionDecision(
            SubmissionStatus.LATE,
            selected_push=selected,
            evidence_source=SubmissionEvidenceSource.PUSH_EVENT_CONFIRMED,
            selected_sha=selected.head_sha,
            selected_timestamp=selected.created_at,
            timestamp_type=SubmissionTimestampType.PUSH_EVENT_CREATED_AT,
        )
    return SubmissionDecision(SubmissionStatus.NOT_SUBMITTED)
