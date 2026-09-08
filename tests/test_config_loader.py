"""private runtime config 전환과 typed configuration validation 테스트."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import github_lab_grader.config_loader as loader
from github_lab_grader.config_loader import (
    ConfigurationError,
    ConfigurationSecurityError,
    RUNTIME_CONFIG_FILENAME,
    ensure_runtime_config_is_private,
    load_global_config,
    load_students,
    load_weekly_rubric,
)


ROOT = Path(__file__).resolve().parents[1]


def example_config() -> dict[str, object]:
    return json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))


def test_public_example_matches_required_schema_with_fictional_accounts() -> None:
    parsed = load_global_config(
        ROOT / "config.example.json", enforce_private_runtime=False
    )
    assert parsed.professor_github == "example-professor"
    assert parsed.assistant_github == "example-assistant"
    assert parsed.github_event_settle_delay_hours == 6
    assert parsed.github_event_history_max_age_days == 30


def test_runtime_configuration_filename_remains_config_json() -> None:
    assert RUNTIME_CONFIG_FILENAME == "config.json"


def test_tracked_runtime_config_is_security_violation(monkeypatch) -> None:
    monkeypatch.setattr(
        loader.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "config.json\n", ""),
    )
    with pytest.raises(ConfigurationSecurityError, match="must not be tracked"):
        ensure_runtime_config_is_private(ROOT / "config.json")


def test_untracked_runtime_config_is_accepted(monkeypatch) -> None:
    monkeypatch.setattr(
        loader.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    ensure_runtime_config_is_private(ROOT / "config.json")


def test_untracked_local_runtime_config_loads(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / RUNTIME_CONFIG_FILENAME
    path.write_text(json.dumps(example_config()), encoding="utf-8")
    monkeypatch.setattr(
        loader.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    parsed = load_global_config(path)
    assert parsed.professor_github == "example-professor"


def test_rubric_json_remains_trackable() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", "rubrics/week01.json"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1
    assert "*.json" not in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_existing_example_rubric_loads_with_aware_timing() -> None:
    rubric = load_weekly_rubric(ROOT / "rubrics/week01.json")
    assert rubric.week == 1
    assert all(
        timing.submission_window_start.utcoffset() is not None
        for timing in rubric.sections.values()
    )


def test_week1_public_rubric_matches_actual_binary_policy() -> None:
    rubric = load_weekly_rubric(ROOT / "rubrics/week01.json")
    expected = datetime.fromisoformat("2026-09-03T23:59:59+09:00")
    assert rubric.sections["01"].effective_deadline == expected
    assert rubric.sections["02"].effective_deadline == expected
    assert rubric.grading.scoring_mode.value == "BINARY"
    assert rubric.grading.assistant_collaborator_required
    assert not rubric.grading.professor_collaborator_required
    assert not rubric.grading.student_id_required and not rubric.grading.student_name_required
    assert not rubric.grading.use_late_window
    assert not rubric.grading.enforce_submission_window_start
    assert not rubric.grading.enforce_submission_branch
    assert [source.value for source in rubric.grading.submission_evidence_sources] == [
        "PUSH_EVENT",
        "COMMIT_HISTORY",
    ]
    assert rubric.score_rules.partial == 0.0


def test_student_csv_rejects_malformed_repository(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text(
        "section,student_id,name,github_id,repository\n"
        "01,EXAMPLE001,Example Student,example-student,not-a-repository\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="invalid repository"):
        load_students(path)


def test_student_csv_allows_missing_github_registration_and_exported_index(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text(
        ",section,student_id,name,github_id,repository\n"
        "0,01,EXAMPLE001,Example Student,,\n",
        encoding="utf-8",
    )
    students = load_students(path, configured_sections=("01",))
    assert len(students) == 1
    assert students[0].github_id == "" and students[0].repository == ""


def test_student_csv_normalizes_https_github_repository_url(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text(
        "section,student_id,name,github_id,repository\n"
        "01,EXAMPLE001,Example Student,example-student,https://github.com/example-student/lab\n",
        encoding="utf-8",
    )
    student = load_students(path)[0]
    assert student.repository == "example-student/lab"


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            "01,EXAMPLE001,One,example-one,example-one/lab\n01,EXAMPLE001,Two,example-two,example-two/lab\n",
            "duplicate student_id",
        ),
        ("99,EXAMPLE001,One,example-one,example-one/lab\n", "unconfigured section"),
        ("01,EXAMPLE001,One,example-one,another-owner/lab\n", "inconsistent github_id"),
    ],
)
def test_student_csv_rejects_operational_roster_conflicts(tmp_path: Path, rows: str, message: str) -> None:
    path = tmp_path / "students.csv"
    path.write_text("section,student_id,name,github_id,repository\n" + rows, encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_students(path, configured_sections=("01",))


def test_tracked_private_student_csv_is_security_violation(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text("section,student_id,name,github_id,repository\n", encoding="utf-8")
    monkeypatch.setattr(
        loader.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "students.csv", ""),
    )
    with pytest.raises(ConfigurationSecurityError, match="students.csv must not be tracked"):
        load_students(path)


@pytest.mark.parametrize("missing_key", ["professor_github", "assistant_github"])
def test_global_config_requires_both_course_accounts(tmp_path: Path, missing_key: str) -> None:
    data = example_config()
    data[missing_key] = ""
    path = tmp_path / "config.example.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=missing_key):
        load_global_config(path, enforce_private_runtime=False)


def test_rubric_rejects_naive_timestamp(tmp_path: Path) -> None:
    data = json.loads((ROOT / "rubrics/week01.json").read_text(encoding="utf-8"))
    data["sections"]["01"]["submission_window_start"] = "2026-09-01T00:00:00"
    path = tmp_path / "week.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="timezone-aware"):
        load_weekly_rubric(path)


def test_rubric_rejects_timing_order_violation(tmp_path: Path) -> None:
    data = json.loads((ROOT / "rubrics/week01.json").read_text(encoding="utf-8"))
    data["sections"]["01"]["submission_window_start"] = "2026-09-04T00:00:00+09:00"
    path = tmp_path / "week.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="submission_window_start"):
        load_weekly_rubric(path)


def test_rubric_rejects_missing_timing_field(tmp_path: Path) -> None:
    data = json.loads((ROOT / "rubrics/week01.json").read_text(encoding="utf-8"))
    del data["sections"]["01"]["effective_deadline"]
    path = tmp_path / "week.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="effective_deadline"):
        load_weekly_rubric(path)


def test_rubric_cannot_disable_mandatory_actor_or_timely_push(tmp_path: Path) -> None:
    data = json.loads((ROOT / "rubrics/week01.json").read_text(encoding="utf-8"))
    data["require_student_push_actor"] = False
    path = tmp_path / "week.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="timely PushEvent actor matching is mandatory"):
        load_weekly_rubric(path)

    data["require_student_push_actor"] = True
    data["grading"]["require_timely_push"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="timely PushEvent actor matching is mandatory"):
        load_weekly_rubric(path)
