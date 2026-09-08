"""canonical 채점 기록의 검증, 원자적 저장, regrade archive를 담당한다."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    CollaboratorStatus,
    CourseConfig,
    GradeResult,
    GradingStatus,
    LateWindowSource,
    ReadmeStatus,
    SubmissionStatus,
    SubmissionEvidenceSource,
    SubmissionTimestampType,
    WeeklyRubric,
)

RECORD_SCHEMA_VERSION = "1"
_SECTION = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_TOP = {"schema_version", "semester", "course", "section", "week", "record_revision", "grading_run_id", "graded_at", "record_created_at", "record_updated_at", "previous_revision", "regrade", "regrade_reason", "timing_policy", "grading_policy", "summary", "students"}


class RecordStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RecordAlreadyExistsError(RecordStoreError):
    def __init__(self) -> None:
        super().__init__("RECORD_ALREADY_EXISTS", "existing record requires explicit regrade")


class RecordNotFoundError(RecordStoreError):
    def __init__(self) -> None:
        super().__init__("RECORD_NOT_FOUND", "canonical record does not exist")


class CorruptedRecordError(RecordStoreError):
    def __init__(self, message: str) -> None:
        super().__init__("CORRUPTED_RECORD", message)


class UnsupportedSchemaError(RecordStoreError):
    def __init__(self, version: object) -> None:
        super().__init__("UNSUPPORTED_SCHEMA", f"unsupported record schema: {version!r}")


class RecordSecurityError(RecordStoreError):
    def __init__(self, message: str) -> None:
        super().__init__("RECORD_SECURITY_ERROR", message)


def _iso(value: datetime, field: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.isoformat()


def _time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise CorruptedRecordError(f"{field} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorruptedRecordError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CorruptedRecordError(f"{field} must be timezone-aware")
    return parsed


def _section(value: object) -> str:
    if not isinstance(value, str) or not _SECTION.fullmatch(value):
        raise RecordStoreError("UNSAFE_RECORD_PATH", "section is not path-safe")
    return value


def _week(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 999:
        raise RecordStoreError("UNSAFE_RECORD_PATH", "week must be a positive integer")
    return value


def _student(result: GradeResult) -> dict[str, Any]:
    coverage = result.event_coverage
    return {
        "student_id": result.student_id, "student_name": result.name,
        "github_id": result.github_id, "repository": result.repository,
        "repository_accessible": result.repository_accessible,
        "repository_default_branch": result.repository_default_branch,
        "grading_status": result.grading_status.value, "score": result.score,
        "max_score": result.max_score, "submission_status": result.submission_status.value,
        "submission_push_event_id": result.submission_push_event_id,
        "submission_push_created_at": _iso(result.submission_push_time, "submission_push_created_at") if result.submission_push_time else None,
        "submission_push_head_sha": result.submission_push_head_sha,
        "submission_ref": result.submission_push_ref,
        "submission_evidence_source": result.submission_evidence_source.value,
        "selected_submission_sha": result.selected_submission_sha,
        "selected_submission_timestamp": _iso(result.selected_submission_timestamp, "selected_submission_timestamp") if result.selected_submission_timestamp else None,
        "selected_submission_timestamp_type": result.selected_submission_timestamp_type.value if result.selected_submission_timestamp_type else None,
        "professor_collaborator_status": result.professor_collaborator.value,
        "assistant_collaborator_status": result.assistant_collaborator.value,
        "professor_collaborator_checked_at": _iso(result.professor_collaborator_checked_at, "professor_collaborator_checked_at") if result.professor_collaborator_checked_at else None,
        "assistant_collaborator_checked_at": _iso(result.assistant_collaborator_checked_at, "assistant_collaborator_checked_at") if result.assistant_collaborator_checked_at else None,
        "readme_status": result.readme_status.value, "readme_exists": result.readme_exists,
        "readme_path": result.readme_path, "readme_lookup_sha": result.selected_submission_sha,
        "student_id_match": result.student_id_found, "student_name_match": result.student_name_found,
        "manual_review_required": result.manual_review_required,
        "manual_review_reason": result.manual_review_reason, "error_code": result.error_code,
        "graded_at": _iso(result.graded_at, "graded_at"),
        "evidence_complete": coverage.assignment_window_covered if coverage else None,
        "event_coverage": None if coverage is None else {
            "fetched_at": _iso(coverage.fetched_at, "coverage.fetched_at"),
            "pages_fetched": coverage.pages_fetched, "events_fetched": coverage.events_fetched,
            "oldest_event_at": _iso(coverage.oldest_event_at, "oldest_event_at") if coverage.oldest_event_at else None,
            "newest_event_at": _iso(coverage.newest_event_at, "newest_event_at") if coverage.newest_event_at else None,
            "reached_documented_limit": coverage.reached_documented_limit,
            "latency_window_complete": coverage.latency_window_complete,
            "assignment_window_covered": coverage.assignment_window_covered,
            "notes": list(coverage.notes),
        },
    }


def _summary(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    students = list(items)
    scores = [item["score"] for item in students]
    return {
        "total_students": len(students),
        "graded_1_0": sum(score == 1.0 for score in scores),
        "graded_0_5": sum(score == 0.5 for score in scores),
        "graded_0_0": sum(score == 0.0 for score in scores),
        "manual_review": sum(bool(item["manual_review_required"]) for item in students),
        "errors": sum(item["grading_status"] == GradingStatus.ERROR.value for item in students),
        "unverifiable": sum(item["submission_status"] == SubmissionStatus.UNVERIFIABLE.value for item in students),
        "ungraded_or_null": sum(score is None for score in scores),
        "earned_score": sum(float(score) for score in scores if score is not None),
        "possible_score": sum(float(item["max_score"]) for item in students),
    }


def build_canonical_record(course: CourseConfig, rubric: WeeklyRubric, section: str, results: Iterable[GradeResult], *, recorded_at: datetime, record_revision: int = 1, previous_revision: int | None = None, regrade: bool = False, regrade_reason: str | None = None, grading_run_id: str | None = None, record_created_at: datetime | None = None) -> dict[str, Any]:
    """GradeResult만으로 future gradebook의 authoritative 입력을 구성한다."""
    section = _section(section)
    week = _week(rubric.week)
    if section not in course.sections or section not in rubric.sections:
        raise ValueError("section is not present in validated configuration")
    if record_revision <= 0 or (regrade and previous_revision != record_revision - 1):
        raise ValueError("invalid record revision relationship")
    values = tuple(results)
    if any(r.semester != course.semester or r.course != course.course or r.section != section or r.week != week for r in values):
        raise ValueError("GradeResult identity does not match section/week record")
    students = [_student(result) for result in values]
    timing = rubric.sections[section]
    resolved = values[0] if values else None
    if resolved is not None and any(
        (r.submission_window_start, r.scheduled_deadline, r.effective_deadline, r.late_window_end, r.late_window_source)
        != (resolved.submission_window_start, resolved.scheduled_deadline, resolved.effective_deadline, resolved.late_window_end, resolved.late_window_source)
        for r in values
    ):
        raise ValueError("GradeResult timing policies are inconsistent")
    record = {
        "schema_version": RECORD_SCHEMA_VERSION, "semester": course.semester,
        "course": course.course, "section": section, "week": week,
        "record_revision": record_revision, "grading_run_id": grading_run_id or str(uuid.uuid4()),
        "graded_at": _iso(max((r.graded_at for r in values), default=recorded_at), "graded_at"),
        "record_created_at": _iso(record_created_at or recorded_at, "record_created_at"),
        "record_updated_at": _iso(recorded_at, "record_updated_at"),
        "previous_revision": previous_revision, "regrade": regrade,
        "regrade_reason": regrade_reason,
        "timing_policy": {
            "submission_window_start": _iso(resolved.submission_window_start if resolved and resolved.submission_window_start else timing.submission_window_start, "submission_window_start"),
            "scheduled_deadline": _iso(resolved.scheduled_deadline if resolved and resolved.scheduled_deadline else timing.scheduled_deadline, "scheduled_deadline"),
            "effective_deadline": _iso(resolved.effective_deadline if resolved and resolved.effective_deadline else timing.effective_deadline, "effective_deadline"),
            "late_window_end": _iso(resolved.late_window_end, "late_window_end") if resolved and resolved.late_window_end else (_iso(timing.late_window_end, "late_window_end") if timing.late_window_end else None),
            "late_window_source": resolved.late_window_source.value if resolved else ("EXPLICIT" if timing.late_window_end else "UNAVAILABLE"),
            "deadline_note": resolved.deadline_note if resolved else timing.deadline_note,
            "submission_branch": rubric.submission_branch,
        },
        "grading_policy": {"max_score": rubric.max_score, "score_rules": {"full": rubric.score_rules.full, "partial": rubric.score_rules.partial, "fail": rubric.score_rules.fail}, "require_student_push_actor": rubric.require_student_push_actor, "scoring_mode": rubric.grading.scoring_mode.value, "require_timely_push": rubric.grading.require_timely_push, "require_root_readme": rubric.grading.readme_required, "required_collaborators": [role for role, required in (("professor", rubric.grading.professor_collaborator_required), ("assistant", rubric.grading.assistant_collaborator_required)) if required], "require_readme_identity": rubric.grading.student_id_required or rubric.grading.student_name_required, "use_late_window": rubric.grading.use_late_window, "enforce_submission_window_start": rubric.grading.enforce_submission_window_start, "enforce_submission_branch": rubric.grading.enforce_submission_branch, "submission_evidence_sources": [source.value for source in rubric.grading.submission_evidence_sources]},
        "summary": _summary(students), "students": students,
    }
    return validate_record(record)


def _validate_student(student: object, index: int) -> None:
    required = {"student_id", "student_name", "github_id", "repository", "grading_status", "score", "max_score", "submission_status", "submission_push_head_sha", "professor_collaborator_status", "assistant_collaborator_status", "readme_status", "student_id_match", "student_name_match", "manual_review_required", "manual_review_reason", "error_code", "graded_at", "event_coverage"}
    if not isinstance(student, dict) or not required.issubset(student):
        raise CorruptedRecordError(f"student result {index} is missing required fields")
    try:
        status = GradingStatus(student["grading_status"])
        SubmissionStatus(student["submission_status"])
        CollaboratorStatus(student["professor_collaborator_status"])
        CollaboratorStatus(student["assistant_collaborator_status"])
        ReadmeStatus(student["readme_status"])
    except (ValueError, TypeError) as exc:
        raise CorruptedRecordError(f"student result {index} has an invalid status") from exc
    _time(student["graded_at"], f"students[{index}].graded_at")
    if student.get("submission_push_created_at") is not None:
        _time(student["submission_push_created_at"], f"students[{index}].submission_push_created_at")
    if student.get("selected_submission_timestamp") is not None:
        _time(student["selected_submission_timestamp"], f"students[{index}].selected_submission_timestamp")
    if "submission_evidence_source" in student:
        try:
            SubmissionEvidenceSource(student["submission_evidence_source"])
            if student.get("selected_submission_timestamp_type") is not None:
                SubmissionTimestampType(student["selected_submission_timestamp_type"])
        except (ValueError, TypeError) as exc:
            raise CorruptedRecordError(f"student result {index} has invalid evidence provenance") from exc
    for field in ("professor_collaborator_checked_at", "assistant_collaborator_checked_at"):
        if student.get(field) is not None:
            _time(student[field], f"students[{index}].{field}")
    coverage = student["event_coverage"]
    if coverage is not None:
        if not isinstance(coverage, dict):
            raise CorruptedRecordError(f"student result {index} has invalid event coverage")
        _time(coverage.get("fetched_at"), f"students[{index}].event_coverage.fetched_at")
        for field in ("oldest_event_at", "newest_event_at"):
            if coverage.get(field) is not None:
                _time(coverage[field], f"students[{index}].event_coverage.{field}")
    score, maximum = student["score"], student["max_score"]
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or maximum <= 0:
        raise CorruptedRecordError(f"student result {index} has invalid max_score")
    if score is None and status not in {GradingStatus.MANUAL_REVIEW, GradingStatus.ERROR}:
        raise CorruptedRecordError(f"student result {index} null score is inconsistent")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= maximum:
            raise CorruptedRecordError(f"student result {index} has invalid score")
        if status in {GradingStatus.MANUAL_REVIEW, GradingStatus.ERROR}:
            raise CorruptedRecordError(f"student result {index} numeric score is inconsistent")
        if (score == 0) != (status is GradingStatus.FAIL):
            raise CorruptedRecordError(f"student result {index} score and grading status disagree")


def validate_record(data: object) -> dict[str, Any]:
    """손상·미지원 schema·점수 의미 혼동을 load 시점에 차단한다."""
    if not isinstance(data, dict):
        raise CorruptedRecordError("record root must be an object")
    if "schema_version" not in data:
        raise CorruptedRecordError("schema_version is required")
    if data["schema_version"] != RECORD_SCHEMA_VERSION:
        raise UnsupportedSchemaError(data["schema_version"])
    missing = _TOP - data.keys()
    if missing:
        raise CorruptedRecordError(f"missing required fields: {', '.join(sorted(missing))}")
    _section(data["section"]); _week(data["week"])
    if not isinstance(data["record_revision"], int) or data["record_revision"] <= 0:
        raise CorruptedRecordError("record_revision must be positive")
    try:
        uuid.UUID(str(data["grading_run_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CorruptedRecordError("grading_run_id must be a UUID") from exc
    for field in ("graded_at", "record_created_at", "record_updated_at"):
        _time(data[field], field)
    if not isinstance(data["timing_policy"], dict) or not isinstance(data["grading_policy"], dict):
        raise CorruptedRecordError("timing_policy and grading_policy must be objects")
    for field in ("submission_window_start", "scheduled_deadline", "effective_deadline"):
        _time(data["timing_policy"].get(field), f"timing_policy.{field}")
    if data["timing_policy"].get("late_window_end") is not None:
        _time(data["timing_policy"]["late_window_end"], "timing_policy.late_window_end")
    try:
        LateWindowSource(data["timing_policy"].get("late_window_source"))
    except (ValueError, TypeError) as exc:
        raise CorruptedRecordError("timing_policy has invalid late_window_source") from exc
    if not isinstance(data["students"], list) or not isinstance(data["summary"], dict):
        raise CorruptedRecordError("students and summary have invalid types")
    for index, student in enumerate(data["students"]):
        _validate_student(student, index)
    if data["summary"] != _summary(data["students"]):
        raise CorruptedRecordError("summary does not match student results")
    revision = data["record_revision"]
    if data["regrade"] is True:
        if data["previous_revision"] != revision - 1:
            raise CorruptedRecordError("regrade revision relationship is invalid")
    elif data["regrade"] is not False or data["previous_revision"] is not None or revision != 1:
        raise CorruptedRecordError("original record revision metadata is invalid")
    return data


class RecordStore:
    """Git-private roots 아래의 section/week canonical record를 관리한다."""
    def __init__(self, records_root: Path = Path("records"), archive_root: Path = Path("archive"), *, project_root: Path = Path("."), tracked_checker: Callable[[Path], bool] | None = None) -> None:
        self.records_root, self.archive_root = records_root.resolve(), archive_root.resolve()
        self.project_root = project_root.resolve()
        self._tracked_checker = tracked_checker or self._git_tracked

    @staticmethod
    def _contained(path: Path, root: Path) -> Path:
        result = path.resolve()
        if not result.is_relative_to(root):
            raise RecordStoreError("UNSAFE_RECORD_PATH", "record path escapes its root")
        return result

    def canonical_path(self, section: object, week: object) -> Path:
        return self._contained(self.records_root / f"section{_section(section)}" / f"week{_week(week):02d}.json", self.records_root)

    def archive_directory(self, section: object, week: object) -> Path:
        return self._contained(self.archive_root / f"section{_section(section)}" / f"week{_week(week):02d}", self.archive_root)

    def _git_tracked(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.project_root)
        except ValueError:
            return False
        try:
            result = subprocess.run(["git", "-C", str(self.project_root), "ls-files", "--error-unmatch", "--", relative.as_posix()], capture_output=True, check=False, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RecordSecurityError("cannot verify record Git privacy") from exc
        return result.returncode == 0

    def _privacy(self, target: Path) -> None:
        if any(self._tracked_checker(path) for path in (self.records_root, self.archive_root, target)):
            raise RecordSecurityError("tracked grading-record path blocks persistence")

    def privacy_preflight(self, section: object, week: object) -> None:
        """GitHub 요청 전에 canonical 출력 경로의 추적 여부를 확인한다."""
        self._privacy(self.canonical_path(section, week))

    def _load_path(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorruptedRecordError("record is not valid UTF-8 JSON") from exc
        return validate_record(data)

    def load(self, section: object, week: object) -> dict[str, Any]:
        path = self.canonical_path(section, week)
        if not path.is_file():
            raise RecordNotFoundError()
        record = self._load_path(path)
        if record["section"] != section or record["week"] != week:
            raise CorruptedRecordError("record identity does not match canonical path")
        return record

    def save(self, course: CourseConfig, rubric: WeeklyRubric, section: str, results: Iterable[GradeResult], *, recorded_at: datetime, regrade: bool = False, regrade_reason: str | None = None, grading_run_id: str | None = None) -> dict[str, Any]:
        target = self.canonical_path(section, rubric.week)
        self._privacy(target)
        old_bytes, old = None, None
        if target.exists():
            old_bytes = target.read_bytes()
            old = self._load_path(target)
            if not regrade:
                raise RecordAlreadyExistsError()
        elif regrade:
            raise RecordNotFoundError()
        revision = 1 if old is None else old["record_revision"] + 1
        record = build_canonical_record(course, rubric, section, results, recorded_at=recorded_at, record_revision=revision, previous_revision=old["record_revision"] if old else None, regrade=old is not None, regrade_reason=regrade_reason if old else None, grading_run_id=grading_run_id, record_created_at=_time(old["record_created_at"], "record_created_at") if old else None)
        content = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode()
        if old is not None and old_bytes is not None:
            self._archive(old, old_bytes)
        # 첫 write도 경쟁 상황에서 기존 canonical 파일을 절대 덮지 않는다.
        self._atomic_write(target, content, replace=old is not None)
        return record

    def _archive(self, record: Mapping[str, Any], content: bytes) -> Path:
        directory = self.archive_directory(record["section"], record["week"])
        self._privacy(directory)
        stamp = _time(record["record_updated_at"], "record_updated_at").strftime("%Y%m%dT%H%M%S%z")
        target = directory / f"revision_{record['record_revision']:03d}_{stamp}_{record['grading_run_id']}.json"
        self._atomic_write(target, content, replace=False)
        if target.read_bytes() != content:
            raise RecordStoreError("ARCHIVE_WRITE_FAILED", "archive verification failed")
        return target

    @staticmethod
    def _atomic_write(target: Path, content: bytes, *, replace: bool = True) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name); handle.write(content); handle.flush(); os.fsync(handle.fileno())
            if replace:
                os.replace(temporary, target)
            else:
                os.link(temporary, target); temporary.unlink()
        except FileExistsError as exc:
            raise RecordStoreError("ARCHIVE_COLLISION", "archive path already exists") from exc
        except OSError as exc:
            raise RecordStoreError("ATOMIC_WRITE_FAILED", "atomic record write failed") from exc
        finally:
            if temporary is not None and temporary.exists():
                try: temporary.unlink()
                except OSError: pass

    def list_records(self) -> tuple[dict[str, Any], ...]:
        if not self.records_root.exists():
            return ()
        records, identities = [], set()
        for path in sorted(self.records_root.rglob("*.json")):
            record = self._load_path(path)
            identity = (record["semester"], record["course"], record["section"], record["week"])
            if identity in identities:
                raise RecordStoreError("DUPLICATE_RECORD", "multiple canonical records share an identity")
            identities.add(identity); records.append(record)
        return tuple(records)
