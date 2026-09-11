"""Canonical record을 바꾸지 않는 private human-approved score adjustment layer."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .gradebook import CompletionStatus, SectionGradebook, StudentGradebookRow, WeekGrade, WeekReportStatus
from .models import CourseConfig, ScoringMode, Student, WeeklyRubric


class ManualGradeAdjustmentError(ValueError):
    """Private adjustment CSV가 effective grade에 안전하게 적용될 수 없을 때 사용한다."""


@dataclass(frozen=True, slots=True)
class ManualGradeAdjustment:
    section: str
    week: int
    student_id: str
    score: float
    reason: str


_FIELDS = ("section", "week", "student_id", "score", "reason")


def load_manual_grade_adjustments(
    path: Path,
    course: CourseConfig,
    students: Iterable[Student],
    rubrics: Mapping[int, WeeklyRubric],
) -> tuple[ManualGradeAdjustment, ...]:
    """없으면 빈 목록을 반환하고, 존재하면 roster/rubric까지 함께 검증한다."""

    if not path.exists():
        return ()
    roster = {(student.section, student.student_id) for student in students}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _FIELDS:
                raise ManualGradeAdjustmentError("manual adjustment CSV header is invalid")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ManualGradeAdjustmentError("manual adjustment CSV cannot be read") from exc
    values: list[ManualGradeAdjustment] = []
    for index, row in enumerate(rows, start=2):
        try:
            section = row["section"].strip()
            week = int(row["week"])
            student_id = row["student_id"].strip()
            score = float(row["score"])
            reason = row["reason"].strip()
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            raise ManualGradeAdjustmentError(f"manual adjustment row {index} is malformed") from exc
        if section not in course.sections or (section, student_id) not in roster:
            raise ManualGradeAdjustmentError(f"manual adjustment row {index} has unknown student or section")
        rubric = rubrics.get(week)
        if rubric is None or section not in rubric.sections:
            raise ManualGradeAdjustmentError(f"manual adjustment row {index} has invalid week")
        if not math.isfinite(score) or not 0 <= score <= rubric.max_score:
            raise ManualGradeAdjustmentError(f"manual adjustment row {index} score is out of range")
        allowed = {rubric.score_rules.full, rubric.score_rules.fail}
        if rubric.grading.scoring_mode is not ScoringMode.BINARY:
            allowed.add(rubric.score_rules.partial)
        if score not in allowed:
            raise ManualGradeAdjustmentError(f"manual adjustment row {index} score is not allowed by rubric")
        if not reason:
            raise ManualGradeAdjustmentError(f"manual adjustment row {index} reason is required")
        values.append(ManualGradeAdjustment(section, week, student_id, score, reason))
    keys = {(item.section, item.week, item.student_id) for item in values}
    if len(keys) != len(values):
        raise ManualGradeAdjustmentError("manual adjustment CSV has duplicate keys")
    return tuple(values)


def apply_manual_grade_adjustments(
    gradebooks: Iterable[SectionGradebook], adjustments: Iterable[ManualGradeAdjustment]
) -> tuple[SectionGradebook, ...]:
    """Pure effective-grade projection; canonical evidence와 automatic score는 보존한다."""

    lookup = {(item.section, item.week, item.student_id): item for item in adjustments}
    books: list[SectionGradebook] = []
    for book in gradebooks:
        rows: list[StudentGradebookRow] = []
        for row in book.rows:
            weeks: list[WeekGrade] = []
            for item in row.weeks:
                adjustment = lookup.get((book.section, item.week, row.student_id))
                automatic = item.automatic_score if item.automatic_score is not None else item.score
                weeks.append(
                    replace(
                        item,
                        score=adjustment.score if adjustment else automatic,
                        automatic_score=automatic,
                        adjustment_score=adjustment.score if adjustment else None,
                        resolution_source="MANUAL_ADJUSTMENT" if adjustment else "AUTOMATIC",
                        adjustment_reason=adjustment.reason if adjustment else None,
                        report_status=WeekReportStatus.RECORDED if adjustment else item.report_status,
                    )
                )
            earned = sum(item.score for item in weeks if item.score is not None)
            resolved_possible = sum(item.max_score or 0.0 for item in weeks if item.score is not None)
            manual = sum(item.report_status is WeekReportStatus.MANUAL_REVIEW for item in weeks)
            errors = sum(item.report_status is WeekReportStatus.ERROR for item in weeks)
            complete = (
                all(week in {item.week for item in weeks} for week in book.expected_weeks)
                and all(item.score is not None for item in weeks)
                and not any(issue.student_id in {None, row.student_id} for issue in book.issues)
                and resolved_possible > 0
            )
            completion = CompletionStatus.COMPLETE if complete else (
                CompletionStatus.REVIEW_REQUIRED if manual or errors else CompletionStatus.INCOMPLETE
            )
            final = earned / resolved_possible * book.final_practice_weight if complete else None
            rows.append(replace(row, weeks=tuple(weeks), earned_score=earned, resolved_possible_score=resolved_possible, completion_status=completion, final_weighted_score=final, manual_review_count=manual, error_count=errors))
        books.append(replace(book, rows=tuple(rows)))
    return tuple(books)


def apply_adjustments_to_weekly_records(
    records: Iterable[Mapping[str, Any]], adjustments: Iterable[ManualGradeAdjustment]
) -> tuple[dict[str, Any], ...]:
    """Weekly Excel 전용 immutable-like projection을 만들며 canonical mapping은 바꾸지 않는다."""

    lookup = {(item.section, item.week, item.student_id): item for item in adjustments}
    projected: list[dict[str, Any]] = []
    for record in records:
        copy = dict(record)
        students: list[dict[str, Any]] = []
        for student in record["students"]:
            value = dict(student)
            adjustment = lookup.get((str(record["section"]), int(record["week"]), str(student["student_id"])))
            automatic = value.get("score")
            value.update(
                {
                    "automatic_score": automatic,
                    "manual_adjustment_score": adjustment.score if adjustment else None,
                    "effective_score": adjustment.score if adjustment else automatic,
                    "effective_grade_source": "MANUAL_ADJUSTMENT" if adjustment else "AUTOMATIC",
                    "manual_adjustment_reason": adjustment.reason if adjustment else None,
                }
            )
            students.append(value)
        copy["students"] = students
        projected.append(copy)
    return tuple(projected)
