"""운영 preflight의 blocker, warning, privacy-safe summary 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from github_lab_grader.auth import AuthCredential, AuthSource
from github_lab_grader.preflight import PreflightSeverity, run_preflight


ROOT = Path(__file__).resolve().parents[1]


class Auth:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def get_credential(self):
        return AuthCredential("fictional-token", AuthSource.ENVIRONMENT) if self.available else None


def inputs(tmp_path: Path, *, missing_registration: bool = False) -> tuple[Path, Path, Path]:
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config["sections"] = ["01"]
    config_path = tmp_path / "config.example.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    roster_path = tmp_path / "students.example.csv"
    github = "" if missing_registration else "example-student"
    repository = "" if missing_registration else "example-student/lab"
    roster_path.write_text(
        f"section,student_id,name,github_id,repository\n01,EXAMPLE001,Example Student,{github},{repository}\n",
        encoding="utf-8",
    )
    rubrics = tmp_path / "rubrics"
    rubrics.mkdir()
    rubric = json.loads((ROOT / "rubrics/week01.json").read_text(encoding="utf-8"))
    rubric["sections"] = {"01": rubric["sections"]["01"]}
    (rubrics / "week01.json").write_text(json.dumps(rubric), encoding="utf-8")
    return config_path, roster_path, rubrics


def test_preflight_missing_registration_is_warning_not_blocker(tmp_path: Path) -> None:
    config, roster, rubrics = inputs(tmp_path, missing_registration=True)
    report = run_preflight(1, "01", Auth(), config_path=config, roster_path=roster, rubrics_root=rubrics)
    assert report.ready
    missing = next(item for item in report.items if item.code == "MISSING_REPOSITORY_INFO")
    assert missing.severity is PreflightSeverity.WARNING
    assert all("EXAMPLE001" not in item.message for item in report.items)
    boundary = next(item for item in report.items if item.code == "SUBMISSION_START_BOUNDARY")
    assert boundary.message.endswith("NOT_ENFORCED")


def test_preflight_auth_failure_is_blocker(tmp_path: Path) -> None:
    config, roster, rubrics = inputs(tmp_path)
    report = run_preflight(1, "01", Auth(False), config_path=config, roster_path=roster, rubrics_root=rubrics)
    assert not report.ready
    assert any(item.code == "AUTH_UNAVAILABLE" for item in report.items)


def test_preflight_unknown_section_is_blocker(tmp_path: Path) -> None:
    config, roster, rubrics = inputs(tmp_path)
    report = run_preflight(1, "99", Auth(), config_path=config, roster_path=roster, rubrics_root=rubrics)
    assert not report.ready
    assert any(item.code == "SECTION_UNKNOWN" for item in report.items)
