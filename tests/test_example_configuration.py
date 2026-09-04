from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from github_lab_grader.github_client import GitHubClientSettings


ROOT = Path(__file__).resolve().parents[1]


def _load_json(relative_path: str) -> dict[str, object]:
    with (ROOT / relative_path).open(encoding="utf-8") as source:
        return json.load(source)


def test_global_and_weekly_sections_are_consistent() -> None:
    config = _load_json("config.json")
    rubric = _load_json("rubrics/week01.json")
    assert set(config["sections"]) == set(rubric["sections"])


def test_github_request_settings_are_valid() -> None:
    config = _load_json("config.json")
    settings = GitHubClientSettings.from_global_config(config)
    assert settings.api_version == config["github_api_version"]
    assert settings.connect_timeout_seconds > 0
    assert settings.read_timeout_seconds > 0
    assert settings.max_retries >= 0


def test_weekly_example_uses_aware_ordered_iso_timestamps() -> None:
    rubric = _load_json("rubrics/week01.json")
    for timing in rubric["sections"].values():
        start = datetime.fromisoformat(timing["submission_window_start"])
        scheduled = datetime.fromisoformat(timing["scheduled_deadline"])
        effective = datetime.fromisoformat(timing["effective_deadline"])
        late_end = datetime.fromisoformat(timing["late_window_end"])
        assert all(value.utcoffset() is not None for value in (start, scheduled, effective, late_end))
        assert start <= scheduled <= effective < late_end


def test_score_example_matches_weekly_maximum() -> None:
    rubric = _load_json("rubrics/week01.json")
    assert rubric["score_rules"] == {"full": 1.0, "partial": 0.5, "fail": 0.0}
    assert rubric["score_rules"]["full"] == rubric["max_score"]


def test_students_example_has_only_configured_sections_and_owner_repo_shape() -> None:
    config = _load_json("config.json")
    with (ROOT / "data/students.example.csv").open(encoding="utf-8", newline="") as source:
        students = list(csv.DictReader(source))
    assert students
    assert all(student["section"] in config["sections"] for student in students)
    assert all(repository.count("/") == 1 for repository in (student["repository"] for student in students))


def test_environment_example_contains_no_token_value() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assignments = dict(
        line.split("=", 1)
        for line in lines
        if line and not line.startswith("#") and "=" in line
    )
    assert assignments["GITHUB_TOKEN"] == ""
