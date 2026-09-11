"""Private, explicit administrative grading overrides."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import (
    GradeResolutionSource,
    GradeResult,
    GradingStatus,
    ManualOverrideAction,
    SubmissionStatus,
)


class ManualOverrideError(ValueError):
    """Private override가 안전하게 적용될 수 없을 때 사용한다."""


@dataclass(frozen=True, slots=True)
class ManualOverride:
    week: int
    section: str
    student_id: str
    action: ManualOverrideAction
    reason: str


def load_manual_overrides(path: Path) -> tuple[ManualOverride, ...]:
    """없으면 빈 설정으로 처리하고, 존재하면 엄격하게 private JSON을 검증한다."""

    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManualOverrideError("manual override file is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ManualOverrideError("manual override schema_version must be 1")
    raw = data.get("overrides")
    if not isinstance(raw, list):
        raise ManualOverrideError("manual overrides must be an array")
    values: list[ManualOverride] = []
    for item in raw:
        try:
            if not isinstance(item, dict):
                raise TypeError
            value = ManualOverride(
                week=item["week"],
                section=item["section"],
                student_id=item["student_id"],
                action=ManualOverrideAction(item["action"]),
                reason=item["reason"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManualOverrideError("manual override entry is invalid") from exc
        if (
            isinstance(value.week, bool)
            or not isinstance(value.week, int)
            or value.week <= 0
            or not isinstance(value.section, str)
            or not value.section
            or not isinstance(value.student_id, str)
            or not value.student_id
            or not isinstance(value.reason, str)
            or not value.reason
        ):
            raise ManualOverrideError("manual override entry has invalid values")
        values.append(value)
    identities = {(item.week, item.section, item.student_id) for item in values}
    if len(identities) != len(values):
        raise ManualOverrideError("manual override entries must be unique")
    return tuple(values)


def apply_manual_overrides(
    results: Iterable[GradeResult],
    *,
    overrides: Iterable[ManualOverride],
    previous_record: Mapping[str, Any] | None,
    section: str,
    week: int,
) -> tuple[GradeResult, ...]:
    """명시된 override만 source canonical의 resolved 결과로 치환한다."""

    values = tuple(results)
    relevant = tuple(
        item for item in overrides if item.section == section and item.week == week
    )
    if not relevant:
        return values
    if previous_record is None:
        raise ManualOverrideError("manual override requires a previous canonical record")
    if previous_record.get("section") != section or previous_record.get("week") != week:
        raise ManualOverrideError("manual override source record does not match section/week")
    previous = {
        student.get("student_id"): student
        for student in previous_record.get("students", ())
        if isinstance(student, Mapping)
    }
    by_student = {result.student_id: result for result in values}
    for override in relevant:
        if override.student_id not in by_student:
            raise ManualOverrideError("manual override student is absent from current roster")
        source = previous.get(override.student_id)
        if source is None:
            raise ManualOverrideError("manual override student is absent from previous record")
        if source.get("score") is None:
            raise ManualOverrideError("manual override source result is unresolved")
        if source.get("grading_status") not in {
            GradingStatus.PASS.value,
            GradingStatus.PARTIAL.value,
            GradingStatus.FAIL.value,
        }:
            raise ManualOverrideError("manual override source grading status is unresolved")
    updated: list[GradeResult] = []
    overrides_by_student = {item.student_id: item for item in relevant}
    for result in values:
        override = overrides_by_student.get(result.student_id)
        if override is None:
            updated.append(result)
            continue
        source = previous[result.student_id]
        automatic_score = result.score
        automatic_status = result.grading_status
        automatic_submission = result.submission_status
        automatic_reason = result.error_code or result.manual_review_reason
        result.score = float(source["score"])
        result.grading_status = GradingStatus(source["grading_status"])
        result.manual_review_required = False
        result.manual_review_reason = None
        result.error_code = None
        result.error_message = None
        result.grade_resolution_source = GradeResolutionSource.MANUAL_OVERRIDE
        result.manual_override_action = override.action
        result.manual_override_reason = override.reason
        result.manual_override_source_revision = int(previous_record["record_revision"])
        result.manual_override_source_run_id = str(previous_record["grading_run_id"])
        result.automatic_score_before_override = automatic_score
        result.automatic_grading_status_before_override = automatic_status
        result.automatic_submission_status_before_override = automatic_submission
        result.automatic_reason_before_override = automatic_reason
        updated.append(result)
    return tuple(updated)
