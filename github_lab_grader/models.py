"""Typed domain models shared by grading, persistence, and reporting layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_timing(
    submission_window_start: datetime,
    scheduled_deadline: datetime,
    effective_deadline: datetime,
    late_window_end: datetime | None,
) -> None:
    for field_name, value in (
        ("submission_window_start", submission_window_start),
        ("scheduled_deadline", scheduled_deadline),
        ("effective_deadline", effective_deadline),
    ):
        _require_aware(value, field_name)
    if late_window_end is not None:
        _require_aware(late_window_end, "late_window_end")
    if submission_window_start > scheduled_deadline:
        raise ValueError("submission_window_start must not be after scheduled_deadline")
    if scheduled_deadline > effective_deadline:
        raise ValueError("scheduled_deadline must not be after effective_deadline")
    if late_window_end is not None and effective_deadline >= late_window_end:
        raise ValueError("late_window_end must be after effective_deadline")


class CollaboratorStatus(StrEnum):
    ACTIVE = "ACTIVE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class SubmissionStatus(StrEnum):
    ON_TIME = "ON_TIME"
    EXTENDED_ON_TIME = "EXTENDED_ON_TIME"
    LATE = "LATE"
    NOT_SUBMITTED = "NOT_SUBMITTED"
    UNVERIFIABLE = "UNVERIFIABLE"
    ERROR = "ERROR"


class GradingStatus(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ERROR = "ERROR"


class LateWindowSource(StrEnum):
    EXPLICIT = "EXPLICIT"
    NEXT_WEEK_DERIVED = "NEXT_WEEK_DERIVED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class Student:
    section: str
    student_id: str
    name: str
    github_id: str
    repository: str


@dataclass(frozen=True, slots=True)
class SectionDeadline:
    submission_window_start: datetime
    scheduled_deadline: datetime
    effective_deadline: datetime
    late_window_end: datetime | None
    deadline_note: str = ""

    def __post_init__(self) -> None:
        _validate_timing(
            self.submission_window_start,
            self.scheduled_deadline,
            self.effective_deadline,
            self.late_window_end,
        )


@dataclass(frozen=True, slots=True)
class ResolvedSectionDeadline:
    submission_window_start: datetime
    scheduled_deadline: datetime
    effective_deadline: datetime
    late_window_end: datetime | None
    late_window_source: LateWindowSource
    deadline_note: str = ""

    def __post_init__(self) -> None:
        _validate_timing(
            self.submission_window_start,
            self.scheduled_deadline,
            self.effective_deadline,
            self.late_window_end,
        )
        if self.late_window_source is LateWindowSource.UNAVAILABLE:
            if self.late_window_end is not None:
                raise ValueError("UNAVAILABLE late-window source requires a null late_window_end")
        elif self.late_window_end is None:
            raise ValueError("A resolved explicit or derived late window requires late_window_end")


@dataclass(frozen=True, slots=True)
class GradingRules:
    professor_collaborator_required: bool = True
    assistant_collaborator_required: bool = True
    readme_required: bool = True
    student_id_required: bool = True
    student_name_required: bool = True


@dataclass(frozen=True, slots=True)
class ScoreRules:
    full: float
    partial: float
    fail: float


@dataclass(frozen=True, slots=True)
class WeeklyRubric:
    week: int
    title: str
    max_score: float
    submission_branch: str
    require_student_push_actor: bool
    sections: dict[str, SectionDeadline]
    grading: GradingRules
    score_rules: ScoreRules
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class PushRecord:
    event_id: str
    actor: str
    created_at: datetime
    ref: str
    head_sha: str
    before_sha: str
    push_id: int | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class EventCoverage:
    fetched_at: datetime
    pages_fetched: int
    events_fetched: int
    oldest_event_at: datetime | None
    newest_event_at: datetime | None
    reached_documented_limit: bool
    latency_window_complete: bool
    assignment_window_covered: bool
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.fetched_at, "fetched_at")
        if self.oldest_event_at is not None:
            _require_aware(self.oldest_event_at, "oldest_event_at")
        if self.newest_event_at is not None:
            _require_aware(self.newest_event_at, "newest_event_at")


@dataclass(slots=True)
class GradeResult:
    semester: str
    course: str
    section: str
    week: int
    student_id: str
    name: str
    github_id: str
    repository: str
    repository_accessible: bool | None
    repository_default_branch: str | None
    submission_window_start: datetime
    scheduled_deadline: datetime
    effective_deadline: datetime
    late_window_end: datetime | None
    late_window_source: LateWindowSource
    deadline_note: str
    submission_status: SubmissionStatus
    submission_push_time: datetime | None
    submission_push_actor: str | None
    submission_push_ref: str | None
    submission_push_head_sha: str | None
    submission_push_before_sha: str | None
    submission_push_event_id: str | None
    professor_collaborator: CollaboratorStatus
    assistant_collaborator: CollaboratorStatus
    professor_collaborator_checked_at: datetime | None
    assistant_collaborator_checked_at: datetime | None
    readme_exists: bool | None
    readme_path: str | None
    student_id_found: bool | None
    student_name_found: bool | None
    score: float | None
    max_score: float
    grading_status: GradingStatus
    manual_review_required: bool
    error_code: str | None
    error_message: str | None
    graded_at: datetime
    event_coverage: EventCoverage | None = None
    selected_push: PushRecord | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_timing(
            self.submission_window_start,
            self.scheduled_deadline,
            self.effective_deadline,
            self.late_window_end,
        )
        _require_aware(self.graded_at, "graded_at")
        for field_name, value in (
            ("submission_push_time", self.submission_push_time),
            ("professor_collaborator_checked_at", self.professor_collaborator_checked_at),
            ("assistant_collaborator_checked_at", self.assistant_collaborator_checked_at),
        ):
            if value is not None:
                _require_aware(value, field_name)
        if self.manual_review_required and self.score is not None:
            raise ValueError("manual-review results must not contain an automatic score")
