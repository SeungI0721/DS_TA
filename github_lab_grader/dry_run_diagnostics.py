"""dry-run GradeResult를 변경하지 않고 운영 판단용 집계를 만든다."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from .display_labels import format_component_status, format_display_label


@dataclass(frozen=True, slots=True)
class DryRunDiagnostics:
    score_counts: dict[str, int]
    null_reasons: dict[str, int]
    submission_statuses: dict[str, int]
    timing: dict[str, str | bool | None]
    unresolved_students: tuple[tuple[str, str], ...]
    resolved_zero_students: tuple[tuple[str, str], ...]
    resolved_full_students: tuple[tuple[str, str], ...]
    override_students: tuple[tuple[str, str, int | None, float | None], ...]
    evidence_sources: dict[str, int]
    component_outcomes: dict[str, int]
    component_students: tuple[tuple[str, tuple[Mapping[str, Any], ...], float | None], ...]


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _null_reason(student: Mapping[str, Any]) -> str:
    error_code = student.get("error_code")
    submission = str(student.get("submission_status") or "")
    grading = str(student.get("grading_status") or "")
    if error_code == "MISSING_REPOSITORY_INFO":
        return "MISSING_REPOSITORY_INFO"
    if submission in {
        "EVIDENCE_NOT_SETTLED",
        "UNVERIFIABLE",
        "AMBIGUOUS_SUBMISSION",
        "MISSING_REPOSITORY_INFO",
    }:
        return submission
    if error_code:
        return str(error_code)
    if grading == "ERROR":
        return "ERROR"
    return "MANUAL_REVIEW"


def _zero_reason(student: Mapping[str, Any], grading_policy: Mapping[str, Any]) -> str:
    """확정 0점의 최소 운영 원인을 canonical status만으로 선택한다."""

    submission = str(student.get("submission_status") or "")
    if submission == "NOT_SUBMITTED":
        return str(student.get("manual_review_reason") or submission)
    if submission == "LATE":
        return submission
    path_reason = student.get("required_path_failure_reason")
    if path_reason:
        return str(path_reason)
    if student.get("readme_status") == "MISSING":
        return "README_MISSING"
    required = set(grading_policy.get("required_collaborators", ()))
    if "assistant" in required and student.get("assistant_collaborator_status") == "MISSING":
        return "ASSISTANT_COLLABORATOR_MISSING"
    if "professor" in required and student.get("professor_collaborator_status") == "MISSING":
        return "PROFESSOR_COLLABORATOR_MISSING"
    error_code = student.get("error_code")
    return str(error_code) if error_code else str(student.get("grading_status") or "FAIL")


def build_dry_run_diagnostics(
    record: Mapping[str, Any],
    *,
    settle_delay_hours: float,
    current_time: datetime,
) -> DryRunDiagnostics:
    """canonical-compatible in-memory record에서 결정적인 진단 snapshot을 만든다."""

    students = tuple(record["students"])
    scores = [student.get("score") for student in students]
    component_mode = record.get("grading_policy", {}).get("scoring_mode") == "COMPONENT_SUM"
    labels = ("1.00", "0.75", "0.50", "0.25", "0.00") if component_mode else ("1.0", "0.5", "0.0")
    score_counts = {
        **{label: sum(score == float(label) for score in scores) for label in labels},
        "null": sum(score is None for score in scores),
    }
    null_students = tuple(student for student in students if student.get("score") is None)
    reasons = Counter(_null_reason(student) for student in null_students)
    submissions = Counter(str(student["submission_status"]) for student in students)
    evidence_sources = Counter(
        str(student.get("submission_evidence_source") or "INSUFFICIENT_EVIDENCE")
        for student in students
    )
    timing_policy = record["timing_policy"]
    effective = _time(timing_policy.get("effective_deadline"))
    late_end = _time(timing_policy.get("late_window_end"))
    delay = timedelta(hours=settle_delay_hours)
    effective_settle = effective + delay if effective else None
    grading_policy = record.get("grading_policy", {})
    late_window_required = bool(grading_policy.get("use_late_window", True))
    start_boundary_enforced = bool(
        record.get("grading_policy", {}).get("enforce_submission_window_start", True)
    )
    late_settle = late_end + delay if late_end else None
    absence_settle = late_settle if late_window_required else effective_settle
    timing: dict[str, str | bool | None] = {
        "submission_start_boundary": (
            timing_policy.get("submission_window_start")
            if start_boundary_enforced
            else "NOT_ENFORCED"
        ),
        "scheduled_deadline": timing_policy.get("scheduled_deadline"),
        "effective_deadline": timing_policy.get("effective_deadline"),
        "late_window_end": timing_policy.get("late_window_end"),
        "effective_deadline_settle_time": effective_settle.isoformat() if effective_settle else None,
        "late_window_end_settle_time": late_settle.isoformat() if late_settle else None,
        "current_grading_time": current_time.isoformat(),
        "scoring_cutoff": timing_policy.get("effective_deadline"),
        "late_window_required_by_rubric": late_window_required,
        "accepted_submission_evidence_settled": bool(effective_settle and current_time >= effective_settle),
        "absence_late_evidence_settled": bool(absence_settle and current_time >= absence_settle),
    }
    unresolved = tuple((str(student["student_id"]), _null_reason(student)) for student in null_students)
    zero_students = tuple(
        (str(student["student_id"]), _zero_reason(student, grading_policy))
        for student in students
        if student.get("score") == 0.0
    )
    full_students = tuple(
        (str(student["student_id"]), str(student.get("submission_evidence_source") or "INSUFFICIENT_EVIDENCE"))
        for student in students
        if student.get("score") == 1.0
    )
    overrides = tuple(
        (
            str(student["student_id"]),
            str(student.get("manual_override_action") or "MANUAL_OVERRIDE"),
            student.get("manual_override_source_revision"),
            student.get("score"),
        )
        for student in students
        if student.get("grade_resolution_source") == "MANUAL_OVERRIDE"
    )
    component_results = tuple(
        component
        for student in students
        for component in student.get("component_results", ())
    )
    component_outcomes = Counter(str(item.get("status")) for item in component_results)
    component_students = tuple(
        (
            str(student["student_id"]),
            tuple(student.get("component_results", ())),
            student.get("score"),
        )
        for student in students
        if student.get("component_results")
    )
    return DryRunDiagnostics(
        score_counts,
        dict(sorted(reasons.items())),
        dict(sorted(submissions.items())),
        timing,
        unresolved,
        zero_students,
        full_students,
        overrides,
        dict(sorted(evidence_sources.items())),
        dict(sorted(component_outcomes.items())),
        component_students,
    )


def format_dry_run_diagnostics(diagnostics: DryRunDiagnostics, *, details: bool = False) -> tuple[str, ...]:
    """PII를 기본 출력하지 않는 안정적인 CLI line 목록을 반환한다."""

    labels = tuple(key for key in diagnostics.score_counts if key != "null")
    lines = ["확정 점수:"]
    lines.extend(f"  {label}: {diagnostics.score_counts[label]}" for label in labels)
    lines.extend(["미확정 점수:", f"  null: {diagnostics.score_counts['null']}"])
    if diagnostics.component_outcomes:
        lines.append("실습별 판정:")
        lines.extend(
            f"  {format_component_status(status)}: {diagnostics.component_outcomes.get(status, 0)}"
            for status in ("PASS", "FAIL", "UNVERIFIABLE")
        )
    lines.append("미확정 사유:")
    lines.extend(f"  {format_display_label(key)}: {value}" for key, value in diagnostics.null_reasons.items())
    if not diagnostics.null_reasons:
        lines.append("  none: 0")
    lines.append("제출 상태:")
    lines.extend(f"  {format_display_label(key)}: {value}" for key, value in diagnostics.submission_statuses.items())
    lines.append("제출 증거:")
    lines.extend(f"  {format_display_label(key)}: {value}" for key, value in diagnostics.evidence_sources.items())
    lines.append(f"수동 예외 적용: {len(diagnostics.override_students)}")
    lines.append("시각 판정 정보:")
    for key, value in diagnostics.timing.items():
        if isinstance(value, bool):
            value = "YES" if value else "NO"
        lines.append(f"  {key}: {value if value is not None else 'UNAVAILABLE'}")
    if diagnostics.timing["late_window_required_by_rubric"] and not diagnostics.timing["absence_late_evidence_settled"]:
        lines.append("지각 제출 구간 미확정 (LATE_WINDOW_NOT_SETTLED): 제출이 확인되지 않은 학생을 아직 LATE 또는 NOT_SUBMITTED로 확정할 수 없습니다.")
    if details:
        if diagnostics.component_students:
            lines.append("학생별 실습 상세:")
            for student_id, components, total in diagnostics.component_students:
                lines.append(f"  {student_id}:")
                for component in components:
                    score = component.get("score")
                    score_text = "null" if score is None else f"{float(score):.2f}"
                    reason = component.get("reason")
                    lines.extend((
                        f"    {component.get('project_path')} 실습{component.get('practice_number')}",
                        f"      결과: {format_component_status(component.get('status'))}",
                        f"      점수: {score_text} / {float(component.get('max_score', 0)):.2f}",
                        f"      사유: {format_display_label(reason)}",
                    ))
                lines.append(
                    f"    total={'null' if total is None else f'{float(total):.2f}'}"
                )
        lines.append("수동 예외 적용 학생:")
        lines.extend(
            f"  {student_id}: {format_display_label(action)} source_revision={revision} score={score}"
            for student_id, action, revision, score in diagnostics.override_students
        )
        if not diagnostics.override_students:
            lines.append("  none")
        lines.append("확정 0.0 학생:")
        lines.extend(
            f"  {student_id}: {format_display_label(reason)}"
            for student_id, reason in diagnostics.resolved_zero_students
        )
        if not diagnostics.resolved_zero_students:
            lines.append("  none")
        lines.append("확정 1.0 학생:")
        lines.extend(
            f"  {student_id}: {format_display_label(source)}"
            for student_id, source in diagnostics.resolved_full_students
        )
        if not diagnostics.resolved_full_students:
            lines.append("  none")
        lines.append("미확정 학생:")
        lines.extend(f"  {student_id}: {format_display_label(reason)}" for student_id, reason in diagnostics.unresolved_students)
        if not diagnostics.unresolved_students:
            lines.append("  none")
    return tuple(lines)
