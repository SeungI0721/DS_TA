"""dry-run 집계, 원인 분류, timing 출력의 순수 로직 테스트."""

from copy import deepcopy
from datetime import UTC, datetime

from github_lab_grader.dry_run_diagnostics import build_dry_run_diagnostics, format_dry_run_diagnostics


NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def record():
    return {
        "timing_policy": {
            "submission_window_start": "2026-09-01T00:00:00+00:00",
            "scheduled_deadline": "2026-09-02T00:00:00+00:00",
            "effective_deadline": "2026-09-03T00:00:00+00:00",
            "late_window_end": "2026-09-08T00:00:00+00:00",
        },
        "grading_policy": {
            "required_collaborators": ["assistant"],
            "use_late_window": True,
            "enforce_submission_window_start": True,
        },
        "students": [
            {"student_id": "EXAMPLE001", "score": 1.0, "submission_status": "ON_TIME", "grading_status": "PASS", "error_code": None},
            {"student_id": "EXAMPLE002", "score": 0.5, "submission_status": "EXTENDED_ON_TIME", "grading_status": "PARTIAL", "error_code": None},
            {"student_id": "EXAMPLE003", "score": 0.0, "submission_status": "LATE", "grading_status": "FAIL", "error_code": None},
            {"student_id": "EXAMPLE004", "score": None, "submission_status": "MISSING_REPOSITORY_INFO", "grading_status": "MANUAL_REVIEW", "error_code": "MISSING_REPOSITORY_INFO"},
            {"student_id": "EXAMPLE005", "score": None, "submission_status": "EVIDENCE_NOT_SETTLED", "grading_status": "MANUAL_REVIEW", "error_code": None},
            {"student_id": "EXAMPLE006", "score": None, "submission_status": "UNVERIFIABLE", "grading_status": "MANUAL_REVIEW", "error_code": None},
            {"student_id": "EXAMPLE007", "score": None, "submission_status": "ERROR", "grading_status": "ERROR", "error_code": "API_ERROR"},
        ],
    }


def test_score_and_null_reason_breakdowns_keep_actual_zero_resolved() -> None:
    diagnostics = build_dry_run_diagnostics(record(), settle_delay_hours=6, current_time=NOW)
    assert diagnostics.score_counts == {"1.0": 1, "0.5": 1, "0.0": 1, "null": 4}
    assert diagnostics.null_reasons == {
        "API_ERROR": 1,
        "EVIDENCE_NOT_SETTLED": 1,
        "MISSING_REPOSITORY_INFO": 1,
        "UNVERIFIABLE": 1,
    }
    assert sum(diagnostics.null_reasons.values()) == diagnostics.score_counts["null"]


def test_submission_and_timing_diagnostics_explain_unsettled_late_window() -> None:
    diagnostics = build_dry_run_diagnostics(record(), settle_delay_hours=6, current_time=NOW)
    assert diagnostics.submission_statuses["ON_TIME"] == 1
    assert diagnostics.submission_statuses["MISSING_REPOSITORY_INFO"] == 1
    assert diagnostics.timing["accepted_submission_evidence_settled"] is True
    assert diagnostics.timing["absence_late_evidence_settled"] is False
    lines = format_dry_run_diagnostics(diagnostics)
    assert any(line.startswith("LATE_WINDOW_NOT_SETTLED:") for line in lines)
    assert not any("EXAMPLE004" in line for line in lines)


def test_details_are_minimal_and_diagnostics_do_not_mutate_results() -> None:
    original = record()
    before = deepcopy(original)
    diagnostics = build_dry_run_diagnostics(original, settle_delay_hours=6, current_time=NOW)
    lines = format_dry_run_diagnostics(diagnostics, details=True)
    assert original == before
    assert "  EXAMPLE004: MISSING_REPOSITORY_INFO" in lines
    assert all("token" not in line.lower() for line in lines)


def test_details_list_resolved_zero_reason_separately_without_sensitive_fields() -> None:
    value = record()
    value["students"][2].update(
        {
            "submission_status": "ON_TIME",
            "readme_status": "MISSING",
            "repository": "private-owner/private-repository",
            "credential": "secret-value",
        }
    )
    diagnostics = build_dry_run_diagnostics(value, settle_delay_hours=6, current_time=NOW)
    before_counts = dict(diagnostics.score_counts)
    aggregate = format_dry_run_diagnostics(diagnostics)
    details = format_dry_run_diagnostics(diagnostics, details=True)
    assert "  EXAMPLE003: README_MISSING" in details
    assert "  EXAMPLE004: MISSING_REPOSITORY_INFO" in details
    assert "  EXAMPLE001: INSUFFICIENT_EVIDENCE" in details
    assert not any("EXAMPLE003" in line for line in aggregate)
    assert diagnostics.score_counts == before_counts == {"1.0": 1, "0.5": 1, "0.0": 1, "null": 4}
    joined = "\n".join(details)
    assert "private-owner" not in joined and "secret-value" not in joined
    assert diagnostics.evidence_sources["INSUFFICIENT_EVIDENCE"] == 7


def test_zero_reason_uses_required_assistant_collaborator_status() -> None:
    value = record()
    value["students"][2].update(
        {
            "submission_status": "ON_TIME",
            "readme_status": "NOT_CHECKED",
            "assistant_collaborator_status": "MISSING",
        }
    )
    diagnostics = build_dry_run_diagnostics(value, settle_delay_hours=6, current_time=NOW)
    assert diagnostics.resolved_zero_students == (("EXAMPLE003", "ASSISTANT_COLLABORATOR_MISSING"),)


def test_zero_reason_preserves_required_path_failure() -> None:
    value = record()
    value["students"][2].update(
        {
            "submission_status": "ON_TIME",
            "required_path_failure_reason": "PROJECT_README_MISSING",
        }
    )
    diagnostics = build_dry_run_diagnostics(
        value, settle_delay_hours=6, current_time=NOW
    )
    assert diagnostics.resolved_zero_students == (
        ("EXAMPLE003", "PROJECT_README_MISSING"),
    )


def test_details_show_manual_override_without_repository_data() -> None:
    value = record()
    value["students"][0].update(
        {
            "grade_resolution_source": "MANUAL_OVERRIDE",
            "manual_override_action": "PRESERVE_PREVIOUS_CANONICAL_RESULT",
            "manual_override_source_revision": 2,
            "repository": "private-owner/private-repository",
        }
    )
    diagnostics = build_dry_run_diagnostics(
        value, settle_delay_hours=6, current_time=NOW
    )
    lines = format_dry_run_diagnostics(diagnostics, details=True)
    assert "Manual overrides applied: 1" in lines
    assert any(
        line.startswith("  EXAMPLE001: PRESERVE_PREVIOUS_CANONICAL_RESULT")
        for line in lines
    )
    assert "private-owner" not in "\n".join(lines)


def test_student_level_unknown_failure_still_produces_complete_summary() -> None:
    value = record()
    value["students"].append(
        {"student_id": "EXAMPLE008", "score": None, "submission_status": "ERROR", "grading_status": "ERROR", "error_code": None}
    )
    diagnostics = build_dry_run_diagnostics(value, settle_delay_hours=6, current_time=NOW)
    assert diagnostics.score_counts["null"] == 5
    assert diagnostics.null_reasons["ERROR"] == 1


def test_no_late_window_rubric_uses_effective_settle_without_misleading_warning() -> None:
    value = record()
    value["grading_policy"] = {
        "use_late_window": False,
        "enforce_submission_window_start": False,
    }
    value["timing_policy"]["late_window_end"] = None
    diagnostics = build_dry_run_diagnostics(value, settle_delay_hours=6, current_time=NOW)
    assert diagnostics.timing["scoring_cutoff"] == "2026-09-03T00:00:00+00:00"
    assert diagnostics.timing["late_window_required_by_rubric"] is False
    assert diagnostics.timing["submission_start_boundary"] == "NOT_ENFORCED"
    assert diagnostics.timing["accepted_submission_evidence_settled"] is True
    assert diagnostics.timing["absence_late_evidence_settled"] is True
    assert not any(
        line.startswith("LATE_WINDOW_NOT_SETTLED:")
        for line in format_dry_run_diagnostics(diagnostics)
    )
