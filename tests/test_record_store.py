"""Phase 5 canonical record의 불변성·검증·privacy 경계 테스트."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from github_lab_grader.models import (
    CollaboratorStatus, CourseConfig, GradeResult, GradingRules, GradingStatus,
    LateWindowSource, ReadmeStatus, ScoreRules, SectionDeadline,
    SubmissionStatus, WeeklyRubric,
)
from github_lab_grader.grading_workflow import grade_and_persist
from github_lab_grader.record_store import (
    CorruptedRecordError, RecordAlreadyExistsError, RecordNotFoundError,
    RecordSecurityError, RecordStore, RecordStoreError, UnsupportedSchemaError,
    build_canonical_record, validate_record,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def course(*sections: str) -> CourseConfig:
    return CourseConfig(1, "2026-2", "Data Structures", "example-professor", "example-assistant", "Asia/Seoul", sections or ("01",), 14, 10.0, "2026-03-10", 6, 30, {})


def rubric(section: str = "01", week: int = 1) -> WeeklyRubric:
    return WeeklyRubric(week, "Example", 1.0, "main", True, {section: SectionDeadline(NOW - timedelta(days=3), NOW - timedelta(days=2), NOW - timedelta(days=1), NOW + timedelta(days=1))}, GradingRules(), ScoreRules(1.0, 0.5, 0.0))


def result(score: float | None = 1.0, *, student_id: str = "EXAMPLE001", name: str = "가상학생", section: str = "01", week: int = 1, sha: str = "a" * 40) -> GradeResult:
    if score is None:
        grading, submission, manual = GradingStatus.MANUAL_REVIEW, SubmissionStatus.UNVERIFIABLE, True
    elif score == 0.0:
        grading, submission, manual = GradingStatus.FAIL, SubmissionStatus.LATE, False
    elif score == 0.5:
        grading, submission, manual = GradingStatus.PARTIAL, SubmissionStatus.ON_TIME, False
    else:
        grading, submission, manual = GradingStatus.PASS, SubmissionStatus.ON_TIME, False
    return GradeResult(
        "2026-2", "Data Structures", section, week, student_id, name,
        f"student-{student_id.lower()}", f"example/{student_id.lower()}", True, "main",
        NOW - timedelta(days=3), NOW - timedelta(days=2), NOW - timedelta(days=1),
        NOW + timedelta(days=1), LateWindowSource.EXPLICIT, "", submission,
        NOW - timedelta(days=2), "student-example", "refs/heads/main", sha, "b" * 40,
        "event-1", CollaboratorStatus.ACTIVE, CollaboratorStatus.ACTIVE, NOW, NOW,
        ReadmeStatus.COMPLETE, True, "README.md", True, True, score, 1.0, grading,
        manual, "evidence incomplete" if manual else None, None, None, NOW,
    )


@pytest.fixture
def store(tmp_path: Path) -> RecordStore:
    return RecordStore(tmp_path / "records", tmp_path / "archive", project_root=tmp_path, tracked_checker=lambda _: False)


def test_first_write_round_trip_preserves_unicode_null_zero_and_sha(store: RecordStore) -> None:
    values = [result(1.0), result(0.5, student_id="EXAMPLE002"), result(0.0, student_id="EXAMPLE003"), result(None, student_id="EXAMPLE004", sha="d" * 40)]
    saved = store.save(course("01"), rubric(), "01", values, recorded_at=NOW)
    loaded = store.load("01", 1)
    assert saved == loaded
    assert loaded["record_revision"] == 1 and loaded["regrade"] is False
    assert loaded["students"][0]["student_name"] == "가상학생"
    assert [item["score"] for item in loaded["students"]] == [1.0, 0.5, 0.0, None]
    assert loaded["students"][3]["submission_push_head_sha"] == "d" * 40
    assert loaded["timing_policy"]["late_window_source"] == "EXPLICIT"
    assert loaded["summary"] == {"total_students": 4, "graded_1_0": 1, "graded_0_5": 1, "graded_0_0": 1, "manual_review": 1, "errors": 0, "unverifiable": 1, "ungraded_or_null": 1, "earned_score": 1.5, "possible_score": 4.0}
    assert "+00:00" in loaded["record_created_at"]


def test_normal_overwrite_is_refused_without_archive(store: RecordStore) -> None:
    store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)
    path = store.canonical_path("01", 1); before = path.read_bytes()
    with pytest.raises(RecordAlreadyExistsError) as caught:
        store.save(course("01"), rubric(), "01", [result(0.0)], recorded_at=NOW)
    assert caught.value.code == "RECORD_ALREADY_EXISTS" and path.read_bytes() == before
    assert not store.archive_root.exists()


def test_two_regrades_archive_exact_prior_revisions(store: RecordStore) -> None:
    first = store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)
    first_bytes = store.canonical_path("01", 1).read_bytes()
    second = store.save(course("01"), rubric(), "01", [result(0.5)], recorded_at=NOW + timedelta(hours=1), regrade=True, regrade_reason="재검토")
    second_bytes = store.canonical_path("01", 1).read_bytes()
    third = store.save(course("01"), rubric(), "01", [result(0.0)], recorded_at=NOW + timedelta(hours=2), regrade=True)
    archives = sorted(store.archive_directory("01", 1).glob("*.json"))
    assert (first["record_revision"], second["record_revision"], third["record_revision"]) == (1, 2, 3)
    assert second["previous_revision"] == 1 and second["regrade_reason"] == "재검토"
    assert len(archives) == 2 and archives[0].read_bytes() == first_bytes and archives[1].read_bytes() == second_bytes
    assert archives[0].name != archives[1].name


def test_regrade_without_existing_record_is_refused(store: RecordStore) -> None:
    with pytest.raises(RecordNotFoundError):
        store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW, regrade=True)


@pytest.mark.parametrize("section", ["../outside", "C:\\private", "/absolute", "01/02"])
def test_malicious_section_is_rejected(store: RecordStore, section: str) -> None:
    with pytest.raises(RecordStoreError, match="path-safe"):
        store.canonical_path(section, 1)


@pytest.mark.parametrize("week", ["../1", "1", -1, 0, True])
def test_malicious_week_is_rejected(store: RecordStore, week: object) -> None:
    with pytest.raises(RecordStoreError):
        store.canonical_path("01", week)


def test_generated_paths_remain_under_roots(store: RecordStore) -> None:
    assert store.canonical_path("17", 9).is_relative_to(store.records_root)
    assert store.archive_directory("17", 9).is_relative_to(store.archive_root)


def test_tracked_record_path_blocks_persistence(tmp_path: Path) -> None:
    store = RecordStore(tmp_path / "records", tmp_path / "archive", tracked_checker=lambda _: True)
    with pytest.raises(RecordSecurityError):
        store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)


def test_malformed_existing_record_is_never_replaced(store: RecordStore) -> None:
    path = store.canonical_path("01", 1); path.parent.mkdir(parents=True); path.write_text("{broken", encoding="utf-8")
    with pytest.raises(CorruptedRecordError):
        store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW, regrade=True)
    assert path.read_text(encoding="utf-8") == "{broken" and not store.archive_root.exists()


def valid_record() -> dict:
    return build_canonical_record(course("01"), rubric(), "01", [result()], recorded_at=NOW)


def test_missing_and_unsupported_schema_are_distinct() -> None:
    missing = valid_record(); del missing["schema_version"]
    with pytest.raises(CorruptedRecordError): validate_record(missing)
    future = valid_record(); future["schema_version"] = "99"
    with pytest.raises(UnsupportedSchemaError): validate_record(future)


def test_naive_timestamp_and_invalid_score_status_are_rejected() -> None:
    naive = valid_record(); naive["record_updated_at"] = "2026-09-04T12:00:00"
    with pytest.raises(CorruptedRecordError, match="timezone-aware"): validate_record(naive)
    invalid = valid_record(); invalid["students"][0]["score"] = None; invalid["summary"] = {**invalid["summary"], "graded_1_0": 0, "ungraded_or_null": 1, "earned_score": 0.0}
    with pytest.raises(CorruptedRecordError, match="null score"): validate_record(invalid)


def test_replacement_failure_preserves_archive_and_old_canonical(store: RecordStore, monkeypatch: pytest.MonkeyPatch) -> None:
    store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)
    target = store.canonical_path("01", 1); old = target.read_bytes()
    original = store._atomic_write
    calls = 0
    def fail_final(path, content, *, replace=True):
        nonlocal calls
        calls += 1
        if replace: raise RecordStoreError("ATOMIC_WRITE_FAILED", "simulated")
        return original(path, content, replace=replace)
    monkeypatch.setattr(store, "_atomic_write", fail_final)
    with pytest.raises(RecordStoreError): store.save(course("01"), rubric(), "01", [result(0.5)], recorded_at=NOW + timedelta(hours=1), regrade=True)
    assert target.read_bytes() == old and len(list(store.archive_root.rglob("*.json"))) == 1
    assert not list(store.records_root.rglob("*.tmp"))


def test_archive_failure_leaves_canonical_unchanged(store: RecordStore, monkeypatch: pytest.MonkeyPatch) -> None:
    store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)
    target = store.canonical_path("01", 1); old = target.read_bytes()
    monkeypatch.setattr(store, "_archive", lambda *_: (_ for _ in ()).throw(RecordStoreError("ARCHIVE_WRITE_FAILED", "simulated")))
    with pytest.raises(RecordStoreError): store.save(course("01"), rubric(), "01", [result(0.5)], recorded_at=NOW + timedelta(hours=1), regrade=True)
    assert target.read_bytes() == old


def test_first_write_failure_leaves_no_final_or_temp(store: RecordStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("github_lab_grader.record_store.os.link", lambda *_: (_ for _ in ()).throw(OSError("simulated")))
    with pytest.raises(RecordStoreError, match="atomic record write failed"):
        store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)
    assert not store.canonical_path("01", 1).exists()
    assert not list(store.records_root.rglob("*.tmp"))


def test_discovery_supports_multiple_sections_and_detects_duplicates(tmp_path: Path) -> None:
    store = RecordStore(tmp_path / "records", tmp_path / "archive", tracked_checker=lambda _: False)
    for section in ("01", "02", "17"):
        store.save(course("01", "02", "17"), rubric(section), section, [result(section=section)], recorded_at=NOW)
    assert [item["section"] for item in store.list_records()] == ["01", "02", "17"]
    duplicate = store.records_root / "duplicate.json"; duplicate.write_bytes(store.canonical_path("01", 1).read_bytes())
    with pytest.raises(RecordStoreError, match="multiple canonical"): store.list_records()


def test_missing_record_is_explicit(store: RecordStore) -> None:
    with pytest.raises(RecordNotFoundError): store.load("01", 1)


def test_token_or_readme_content_is_not_serialized() -> None:
    record = valid_record(); text = json.dumps(record)
    assert "token" not in text.lower() and "readme_content" not in text.lower()


class FakeOrchestrator:
    def __init__(self, values):
        self.values = tuple(values)
        self.calls = 0

    def grade_section_week(self, students, section, rubric, *, next_rubric=None):
        self.calls += 1
        return self.values


def test_workflow_persists_mixed_results_and_regrades(store: RecordStore) -> None:
    values = [result(1.0), result(0.5, student_id="EXAMPLE002"), result(0.0, student_id="EXAMPLE003"), result(None, student_id="EXAMPLE004")]
    fake = FakeOrchestrator(values)
    first = grade_and_persist(fake, store, course("01"), rubric(), [], "01", recorded_at=NOW)
    second = grade_and_persist(fake, store, course("01"), rubric(), [], "01", recorded_at=NOW + timedelta(hours=1), regrade=True)
    assert first.written and second.record["record_revision"] == 2
    assert [item["score"] for item in second.record["students"]] == [1.0, 0.5, 0.0, None]
    assert fake.calls == 2 and len(list(store.archive_root.rglob("*.json"))) == 1


def test_workflow_dry_run_has_no_persistence_side_effect(store: RecordStore) -> None:
    outcome = grade_and_persist(FakeOrchestrator([result()]), store, course("01"), rubric(), [], "01", recorded_at=NOW, dry_run=True)
    assert not outcome.written and outcome.record["summary"]["total_students"] == 1
    assert not store.records_root.exists() and not store.archive_root.exists()


def test_reconstruction_never_calls_grading_orchestrator(store: RecordStore) -> None:
    store.save(course("01"), rubric(), "01", [result()], recorded_at=NOW)
    fake = FakeOrchestrator([])
    assert store.list_records()[0]["record_revision"] == 1
    assert fake.calls == 0
