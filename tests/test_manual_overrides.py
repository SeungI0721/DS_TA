"""Private manual override의 source-record 보존 및 안전 경계 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from github_lab_grader.manual_overrides import (
    ManualOverride,
    ManualOverrideError,
    apply_manual_overrides,
    load_manual_overrides,
)
from github_lab_grader.models import (
    GradeResolutionSource,
    GradingStatus,
    ManualOverrideAction,
    SubmissionStatus,
)
from github_lab_grader.grading_workflow import grade_and_persist
from github_lab_grader.record_store import RecordStore, build_canonical_record
from phase6_helpers import NOW, make_course, make_record, make_result, make_rubric, make_student


def override(student_id: str = "EXAMPLE001") -> ManualOverride:
    return ManualOverride(
        1,
        "01",
        student_id,
        ManualOverrideAction.PRESERVE_PREVIOUS_CANONICAL_RESULT,
        "Repository history is no longer available after approved recreation.",
    )


def automatic(student_id: str = "EXAMPLE001"):
    result = make_result(make_student(student_id), score=None)
    result.grading_status = GradingStatus.ERROR
    result.submission_status = SubmissionStatus.ERROR
    result.error_code = "NOT_FOUND"
    return result


def prior(score: float | None = 1.0, student_id: str = "EXAMPLE001") -> dict:
    course = make_course(weeks=1)
    rubric = make_rubric(1)
    return make_record(
        course,
        rubric,
        results=[make_result(make_student(student_id), score=score)],
        revision=2,
    )


def test_explicit_override_preserves_prior_resolved_result_and_automatic_provenance() -> None:
    result = apply_manual_overrides(
        [automatic()],
        overrides=[override()],
        previous_record=prior(),
        section="01",
        week=1,
    )[0]
    assert result.score == 1.0 and result.grading_status is GradingStatus.PASS
    assert result.grade_resolution_source is GradeResolutionSource.MANUAL_OVERRIDE
    assert result.automatic_score_before_override is None
    assert result.automatic_grading_status_before_override is GradingStatus.ERROR
    assert result.automatic_submission_status_before_override is SubmissionStatus.ERROR
    assert result.automatic_reason_before_override == "NOT_FOUND"


def test_no_override_keeps_current_automatic_result() -> None:
    current = automatic()
    assert apply_manual_overrides(
        [current], overrides=[], previous_record=None, section="01", week=1
    ) == (current,)


@pytest.mark.parametrize("case", ["missing", "student", "unresolved", "scope"])
def test_invalid_override_source_never_invents_a_score(case: str) -> None:
    source, message = {
        "missing": (None, "previous canonical"),
        "student": (prior(student_id="OTHER"), "absent from previous"),
        "unresolved": (prior(score=None), "unresolved"),
        "scope": ({**prior(), "section": "02"}, "does not match"),
    }[case]
    with pytest.raises(ManualOverrideError, match=message):
        apply_manual_overrides(
            [automatic()], overrides=[override()], previous_record=source,
            section="01", week=1,
        )


def test_override_student_absent_from_current_roster_is_rejected() -> None:
    with pytest.raises(ManualOverrideError, match="current roster"):
        apply_manual_overrides(
            [automatic("OTHER")], overrides=[override()], previous_record=prior(),
            section="01", week=1,
        )


def test_malformed_private_override_file_fails_safely(tmp_path: Path) -> None:
    path = tmp_path / "manual_overrides.json"
    path.write_text('{"schema_version": 1, "overrides": [{}]}', encoding="utf-8")
    with pytest.raises(ManualOverrideError, match="invalid"):
        load_manual_overrides(path)


def test_override_file_requires_unique_matching_scope(tmp_path: Path) -> None:
    path = tmp_path / "manual_overrides.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "overrides": [
                    {
                        "week": 1,
                        "section": "01",
                        "student_id": "EXAMPLE001",
                        "action": "PRESERVE_PREVIOUS_CANONICAL_RESULT",
                        "reason": "fictional approved exception",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_manual_overrides(path)
    assert loaded[0].student_id == "EXAMPLE001"
    assert loaded[0].action is ManualOverrideAction.PRESERVE_PREVIOUS_CANONICAL_RESULT


def test_override_provenance_round_trips_in_canonical_record() -> None:
    value = apply_manual_overrides(
        [automatic()], overrides=[override()], previous_record=prior(), section="01", week=1
    )[0]
    record = build_canonical_record(
        make_course(weeks=1), make_rubric(1), "01", [value], recorded_at=NOW
    )
    student = record["students"][0]
    assert student["grade_resolution_source"] == "MANUAL_OVERRIDE"
    assert student["automatic_submission_status_before_override"] == "ERROR"


def test_dry_run_previews_only_explicit_override(tmp_path: Path) -> None:
    course = make_course(weeks=1)
    rubric = make_rubric(1)
    item = make_student()
    store = RecordStore(
        tmp_path / "records", tmp_path / "archive", project_root=tmp_path,
        tracked_checker=lambda _path: False,
    )
    store.save(course, rubric, "01", [make_result(item, score=0.0)], recorded_at=NOW)
    path = tmp_path / "data" / "manual_overrides.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "overrides": [
                    {
                        "week": 1, "section": "01", "student_id": item.student_id,
                        "action": "PRESERVE_PREVIOUS_CANONICAL_RESULT",
                        "reason": "fictional approved exception",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeOrchestrator:
        def grade_section_week(self, *_args, **_kwargs):
            return (automatic(item.student_id),)

    outcome = grade_and_persist(
        FakeOrchestrator(), store, course, rubric, [item], "01", recorded_at=NOW,
        dry_run=True, manual_overrides_path=path,
    )
    assert outcome.written is False
    student = outcome.record["students"][0]
    assert student["score"] == 0.0
    assert student["grade_resolution_source"] == "MANUAL_OVERRIDE"
    assert store.load("01", 1)["record_revision"] == 1
