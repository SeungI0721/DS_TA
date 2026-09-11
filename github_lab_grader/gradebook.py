"""검증된 canonical records만으로 재현 가능한 gradebook 모델을 만든다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping

from .models import CourseConfig, Student, WeeklyRubric
from .record_store import validate_record


class WeekReportStatus(StrEnum):
    RECORDED = "RECORDED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ERROR = "ERROR"
    RECORD_MISSING = "RECORD_MISSING"
    FUTURE_WEEK = "FUTURE_WEEK"


class CompletionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class ReconstructionIssue:
    code: str
    section: str
    student_id: str | None
    week: int | None
    field: str | None
    expected: str | float | None
    actual: str | float | None


@dataclass(frozen=True, slots=True)
class WeekGrade:
    week: int
    score: float | None
    max_score: float | None
    grading_status: str
    submission_status: str | None
    record_revision: int | None
    submission_push_head_sha: str | None
    report_status: WeekReportStatus
    automatic_score: float | None = None
    adjustment_score: float | None = None
    resolution_source: str = "AUTOMATIC"
    adjustment_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StudentGradebookRow:
    section: str
    student_id: str
    name: str
    github_id: str
    repository: str
    weeks: tuple[WeekGrade, ...]
    earned_score: float
    resolved_possible_score: float
    configured_possible_score: float
    completion_status: CompletionStatus
    final_weighted_score: float | None
    manual_review_count: int
    error_count: int


@dataclass(frozen=True, slots=True)
class SectionGradebook:
    semester: str
    course: str
    section: str
    expected_weeks: tuple[int, ...]
    rows: tuple[StudentGradebookRow, ...]
    issues: tuple[ReconstructionIssue, ...]
    final_practice_weight: float


def natural_section_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """앞자리 0을 보존하면서 숫자 조각은 자연 순서로 정렬한다."""
    import re

    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def _missing_status(
    section: str,
    week: int,
    rubrics: Mapping[int, WeeklyRubric],
    as_of: datetime,
) -> WeekReportStatus:
    rubric = rubrics.get(week)
    timing = rubric.sections.get(section) if rubric else None
    if timing is not None and timing.submission_window_start > as_of:
        return WeekReportStatus.FUTURE_WEEK
    return WeekReportStatus.RECORD_MISSING


def _identity(student: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(student["student_name"]), str(student["github_id"]), str(student["repository"])


def build_section_gradebook(
    course: CourseConfig,
    section: str,
    records: Iterable[dict[str, Any]],
    rubrics: Mapping[int, WeeklyRubric],
    roster: Iterable[Student] | None = None,
    *,
    as_of: datetime | None = None,
) -> SectionGradebook:
    """roster는 행 구성을 돕고 점수는 canonical record에서만 읽는다."""

    if section not in course.sections:
        raise ValueError("section is not configured")
    checked_at = as_of or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    expected_weeks = tuple(range(1, course.total_weeks + 1))
    relevant: dict[int, dict[str, Any]] = {}
    for raw in records:
        record = validate_record(raw)
        if record["semester"] != course.semester or record["course"] != course.course:
            continue
        if record["section"] != section:
            continue
        week = int(record["week"])
        if week in relevant:
            raise ValueError("DUPLICATE_RECORD")
        relevant[week] = record

    roster_supplied = roster is not None
    roster_rows = [student for student in (roster or ()) if student.section == section]
    identities: dict[str, tuple[str, str, str]] = {
        student.student_id: (student.name, student.github_id, student.repository)
        for student in roster_rows
    }
    order = [student.student_id for student in roster_rows]
    issues: list[ReconstructionIssue] = []
    by_week: dict[int, dict[str, dict[str, Any]]] = {}
    for week in sorted(relevant):
        record = relevant[week]
        configured = rubrics.get(week)
        canonical_max = float(record["grading_policy"]["max_score"])
        if configured is not None and canonical_max != configured.max_score:
            issues.append(ReconstructionIssue("MAX_SCORE_MISMATCH", section, None, week, "max_score", configured.max_score, canonical_max))
        week_students: dict[str, dict[str, Any]] = {}
        for student in record["students"]:
            student_id = str(student["student_id"])
            student_max = float(student["max_score"])
            if student_max != canonical_max:
                issues.append(ReconstructionIssue("MAX_SCORE_MISMATCH", section, student_id, week, "max_score", canonical_max, student_max))
            current = _identity(student)
            if student_id in identities and identities[student_id] != current:
                for field, expected, actual in zip(("name", "github_id", "repository"), identities[student_id], current):
                    if expected != actual:
                        issues.append(ReconstructionIssue("IDENTITY_MISMATCH", section, student_id, week, field, expected, actual))
            elif student_id not in identities:
                identities[student_id] = current
                order.append(student_id)
                if roster_supplied:
                    issues.append(ReconstructionIssue("CANONICAL_STUDENT_NOT_IN_ROSTER", section, student_id, week, None, None, None))
            week_students[student_id] = student
        by_week[week] = week_students

    roster_ids = {student.student_id for student in roster_rows}
    roster_order = {student.student_id: index for index, student in enumerate(roster_rows)}
    order = sorted(set(order), key=lambda sid: (0, roster_order[sid]) if sid in roster_ids else (1, sid))
    configured_possible = sum(
        rubrics[week].max_score for week in expected_weeks if week in rubrics
    )
    rows: list[StudentGradebookRow] = []
    for student_id in order:
        name, github_id, repository = identities[student_id]
        weeks: list[WeekGrade] = []
        for week in expected_weeks:
            student = by_week.get(week, {}).get(student_id)
            if student is None:
                maximum = rubrics[week].max_score if week in rubrics else None
                status = _missing_status(section, week, rubrics, checked_at)
                weeks.append(WeekGrade(week, None, maximum, status.value, None, None, None, status, None))
                continue
            score = student["score"]
            grading_status = str(student["grading_status"])
            report_status = (
                WeekReportStatus.ERROR if grading_status == "ERROR"
                else WeekReportStatus.MANUAL_REVIEW if score is None
                else WeekReportStatus.RECORDED
            )
            weeks.append(WeekGrade(
                week, float(score) if score is not None else None,
                float(student["max_score"]), grading_status,
                str(student["submission_status"]), relevant[week]["record_revision"],
                student.get("submission_push_head_sha"), report_status,
                float(score) if score is not None else None,
            ))
        earned = sum(item.score for item in weeks if item.score is not None)
        resolved_possible = sum(item.max_score or 0.0 for item in weeks if item.score is not None)
        manual = sum(item.report_status is WeekReportStatus.MANUAL_REVIEW for item in weeks)
        errors = sum(item.report_status is WeekReportStatus.ERROR for item in weeks)
        student_issues = any(issue.student_id in {None, student_id} for issue in issues)
        complete = (
            all(week in rubrics for week in expected_weeks)
            and all(item.score is not None for item in weeks)
            and not student_issues
            and resolved_possible > 0
        )
        completion = CompletionStatus.COMPLETE if complete else (
            CompletionStatus.REVIEW_REQUIRED if manual or errors or student_issues else CompletionStatus.INCOMPLETE
        )
        final_score = earned / resolved_possible * course.final_practice_weight if complete else None
        rows.append(StudentGradebookRow(section, student_id, name, github_id, repository, tuple(weeks), earned, resolved_possible, configured_possible, completion, final_score, manual, errors))
    return SectionGradebook(course.semester, course.course, section, expected_weeks, tuple(rows), tuple(issues), course.final_practice_weight)


def build_all_section_gradebooks(
    course: CourseConfig,
    records: Iterable[dict[str, Any]],
    rubrics: Mapping[int, WeeklyRubric],
    roster: Iterable[Student] | None = None,
    *,
    as_of: datetime | None = None,
) -> tuple[SectionGradebook, ...]:
    """설정된 모든 section을 자연 순서로 독립 재구성한다."""
    cached_records = tuple(records)
    cached_roster = tuple(roster) if roster is not None else None
    return tuple(
        build_section_gradebook(course, section, cached_records, rubrics, cached_roster, as_of=as_of)
        for section in sorted(course.sections, key=natural_section_key)
    )
