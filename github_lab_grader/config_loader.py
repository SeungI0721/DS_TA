"""공개 설정과 비공개 학생 CSV를 typed model로 검증해 읽는다."""

from __future__ import annotations

import csv
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import (
    CourseConfig,
    GradingRules,
    ScoringMode,
    SubmissionEvidenceType,
    ScoreRules,
    SectionDeadline,
    Student,
    WeeklyRubric,
)


class ConfigurationError(ValueError):
    """설정이 없거나 형식 및 내부 관계가 올바르지 않을 때 발생한다."""


class ConfigurationSecurityError(ConfigurationError):
    """비공개 runtime 설정이 Git에 추적되는 보안 위반을 나타낸다."""


_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}$"
)
_GITHUB_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_SECTION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
RUNTIME_CONFIG_FILENAME = "config.json"
PRIVATE_STUDENTS_FILENAME = "students.csv"


def _normalize_repository(value: str, row_number: int) -> str:
    """GitHub 웹 URL 또는 owner/repository 값을 API용 식별자로 정규화한다."""
    if not value:
        return ""
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        parts = parsed.path.strip("/").split("/")
        if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2:
            raise ConfigurationError(f"student CSV row {row_number} has an invalid GitHub repository URL")
        value = f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return value


def ensure_runtime_config_is_private(path: Path) -> None:
    """runtime config가 Git index에 있으면 실제 값과 무관하게 처리를 거부한다."""

    if path.name != RUNTIME_CONFIG_FILENAME:
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "ls-files", "--error-unmatch", "--", path.name],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigurationSecurityError(
            "cannot verify that private course configuration is untracked"
        ) from exc
    if result.returncode == 0:
        raise ConfigurationSecurityError(
            "private course configuration must not be tracked by Git"
        )


def ensure_private_local_file_is_untracked(path: Path) -> None:
    """실제 roster처럼 이름으로 식별되는 private 입력의 Git 추적을 차단한다."""

    if path.name not in {RUNTIME_CONFIG_FILENAME, PRIVATE_STUDENTS_FILENAME}:
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "ls-files", "--error-unmatch", "--", path.name],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigurationSecurityError("cannot verify that private local input is untracked") from exc
    if result.returncode == 0:
        raise ConfigurationSecurityError(f"private {path.name} must not be tracked by Git")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read valid JSON: {path.name}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"JSON root must be an object: {path.name}")
    return data


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigurationError(f"{field_name} must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfigurationError(f"{field_name} must be timezone-aware")
    return parsed


def load_global_config(path: Path, *, enforce_private_runtime: bool = True) -> CourseConfig:
    """전역 과정 설정을 검증하고 settle/retention 정책을 포함해 반환한다."""

    if enforce_private_runtime:
        ensure_runtime_config_is_private(path)
    data = _read_json(path)
    professor = _required_text(data, "professor_github")
    assistant = _required_text(data, "assistant_github")
    if not _GITHUB_ID_PATTERN.fullmatch(professor):
        raise ConfigurationError("professor_github is invalid")
    if not _GITHUB_ID_PATTERN.fullmatch(assistant):
        raise ConfigurationError("assistant_github is invalid")
    timezone_name = _required_text(data, "timezone")
    if timezone_name != "Asia/Seoul":
        raise ConfigurationError("timezone must be Asia/Seoul")
    sections = data.get("sections")
    request = data.get("github_request")
    if not isinstance(sections, list) or not all(isinstance(item, str) for item in sections):
        raise ConfigurationError("sections must be a string array")
    if not isinstance(request, dict):
        raise ConfigurationError("github_request must be an object")
    try:
        return CourseConfig(
            schema_version=int(data["schema_version"]),
            semester=_required_text(data, "semester"),
            course=_required_text(data, "course"),
            professor_github=professor,
            assistant_github=assistant,
            timezone=timezone_name,
            sections=tuple(sections),
            total_weeks=int(data["total_weeks"]),
            final_practice_weight=float(data["final_practice_weight"]),
            github_api_version=_required_text(data, "github_api_version"),
            github_event_settle_delay_hours=float(
                data.get("github_event_settle_delay_hours", 6)
            ),
            github_event_history_max_age_days=float(
                data.get("github_event_history_max_age_days", 30)
            ),
            github_request=dict(request),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid global configuration: {exc}") from exc


def load_students(
    path: Path,
    *,
    enforce_private_runtime: bool = True,
    configured_sections: tuple[str, ...] | None = None,
) -> list[Student]:
    """추적되지 않는 CSV에서 학생별 repository 설정을 검증해 읽는다."""

    if enforce_private_runtime:
        ensure_private_local_file_is_untracked(path)

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ConfigurationError(f"cannot read student CSV: {path.name}") from exc
    required = {"section", "student_id", "name", "github_id", "repository"}
    if not rows:
        return []
    if not required.issubset(rows[0]):
        raise ConfigurationError("student CSV is missing required columns")
    students: list[Student] = []
    student_ids: set[str] = set()
    logical_entries: set[tuple[str, str, str, str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        values = {key: (row.get(key) or "").strip() for key in required}
        values["repository"] = _normalize_repository(values["repository"], row_number)
        if any(not values[key] for key in ("section", "student_id", "name")):
            raise ConfigurationError(f"student CSV row {row_number} has an empty identity value")
        if not _SECTION_PATTERN.fullmatch(values["section"]):
            raise ConfigurationError(f"student CSV row {row_number} has an invalid section")
        if configured_sections is not None and values["section"] not in configured_sections:
            raise ConfigurationError(f"student CSV row {row_number} has an unconfigured section")
        if values["github_id"] and not _GITHUB_ID_PATTERN.fullmatch(values["github_id"]):
            raise ConfigurationError(f"student CSV row {row_number} has an invalid github_id")
        if values["repository"] and not _REPOSITORY_PATTERN.fullmatch(values["repository"]):
            raise ConfigurationError(f"student CSV row {row_number} has an invalid repository")
        if values["github_id"] and values["repository"]:
            owner = values["repository"].split("/", 1)[0]
            if owner.casefold() != values["github_id"].casefold():
                raise ConfigurationError(f"student CSV row {row_number} has inconsistent github_id and repository owner")
        logical = tuple(values[key] for key in ("section", "student_id", "name", "github_id", "repository"))
        if values["student_id"] in student_ids:
            raise ConfigurationError(f"student CSV row {row_number} has a duplicate student_id")
        if logical in logical_entries:
            raise ConfigurationError(f"student CSV row {row_number} duplicates a student entry")
        student_ids.add(values["student_id"])
        logical_entries.add(logical)
        students.append(Student(**values))
    return students


def load_weekly_rubric(path: Path) -> WeeklyRubric:
    """주차 rubric과 section별 timezone-aware 제출 구간을 검증한다."""

    data = _read_json(path)
    sections_data = data.get("sections")
    grading_data = data.get("grading")
    scores_data = data.get("score_rules")
    if not isinstance(sections_data, dict) or not sections_data:
        raise ConfigurationError("rubric sections must be a non-empty object")
    if not isinstance(grading_data, dict) or not isinstance(scores_data, dict):
        raise ConfigurationError("grading and score_rules must be objects")
    sections: dict[str, SectionDeadline] = {}
    try:
        for section, timing in sections_data.items():
            if not isinstance(section, str) or not section or not isinstance(timing, dict):
                raise ConfigurationError("rubric section entry is invalid")
            late_value = timing.get("late_window_end")
            sections[section] = SectionDeadline(
                submission_window_start=_timestamp(
                    timing.get("submission_window_start"), "submission_window_start"
                ),
                scheduled_deadline=_timestamp(
                    timing.get("scheduled_deadline"), "scheduled_deadline"
                ),
                effective_deadline=_timestamp(
                    timing.get("effective_deadline"), "effective_deadline"
                ),
                late_window_end=(
                    _timestamp(late_value, "late_window_end") if late_value is not None else None
                ),
                deadline_note=str(timing.get("deadline_note", "")),
            )
        rubric = WeeklyRubric(
            schema_version=int(data.get("schema_version", 1)),
            week=int(data["week"]),
            title=_required_text(data, "title"),
            max_score=float(data["max_score"]),
            submission_branch=_required_text(data, "submission_branch"),
            require_student_push_actor=bool(data.get("require_student_push_actor", True)),
            sections=sections,
            grading=GradingRules(
                **{
                    **grading_data,
                    "scoring_mode": ScoringMode(
                        grading_data.get("scoring_mode", "IDENTITY_PARTIAL")
                    ),
                    "submission_evidence_sources": tuple(
                        SubmissionEvidenceType(value)
                        for value in grading_data.get(
                            "submission_evidence_sources", ["PUSH_EVENT"]
                        )
                    ),
                }
            ),
            score_rules=ScoreRules(**{key: float(value) for key, value in scores_data.items()}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError(f"invalid weekly rubric: {exc}") from exc
    if rubric.week <= 0 or rubric.max_score <= 0:
        raise ConfigurationError("week and max_score must be positive")
    if not 0 <= rubric.score_rules.fail <= rubric.score_rules.partial <= rubric.score_rules.full:
        raise ConfigurationError("score rules must be ordered")
    if rubric.score_rules.full > rubric.max_score:
        raise ConfigurationError("full score must not exceed max_score")
    return rubric
