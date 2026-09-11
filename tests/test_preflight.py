"""운영 preflight의 blocker, warning, privacy-safe summary 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from github_lab_grader.auth import AuthCredential, AuthSource
from github_lab_grader.preflight import PreflightSeverity, run_preflight
from github_lab_grader.record_store import RecordSecurityError


ROOT = Path(__file__).resolve().parents[1]


class Auth:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def get_credential(self):
        return AuthCredential("fictional-token", AuthSource.ENVIRONMENT) if self.available else None


def inputs(tmp_path: Path, *, missing_registration: bool = False) -> tuple[Path, Path, Path]:
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config["sections"] = ["01"]
    config["operator_confirmations"] = ["professor_github_identity"]
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
    messages = {item.code: item.message for item in report.items}
    assert messages["SCORING_MODE"].endswith("BINARY")
    assert "2026-09-03 23:59 KST" in messages["DEADLINE_NOTE"]
    assert "2026-09-03T23:59:59+09:00" in messages["EFFECTIVE_DEADLINE"]
    assert "NOT_ENFORCED" in messages["SUBMISSION_BRANCH_POLICY"]
    assert messages["REQUIRED_COLLABORATORS"].endswith("professor, assistant")
    assert "(README.md) AND (week01/README.md OR week01-01/README.md)" in messages[
        "REQUIRED_PATH_GROUPS"
    ]
    assert messages["SUBMISSION_EVIDENCE_SOURCES"].endswith(
        "PUSH_EVENT, COMMIT_HISTORY"
    )


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


def test_preflight_requires_private_professor_identity_confirmation(tmp_path: Path) -> None:
    config, roster, rubrics = inputs(tmp_path)
    data = json.loads(config.read_text(encoding="utf-8"))
    data["operator_confirmations"] = []
    config.write_text(json.dumps(data), encoding="utf-8")
    report = run_preflight(
        1, "01", Auth(), config_path=config, roster_path=roster, rubrics_root=rubrics
    )
    assert not report.ready
    blocker = next(
        item for item in report.items if item.code == "OPERATOR_CONFIRMATION_REQUIRED"
    )
    assert blocker.severity is PreflightSeverity.BLOCKER
    assert "github" not in blocker.message.casefold()


def test_preflight_blocks_tracked_private_manual_override(
    monkeypatch, tmp_path: Path
) -> None:
    config, roster, rubrics = inputs(tmp_path)
    monkeypatch.setattr(
        "github_lab_grader.preflight.RecordStore.private_file_preflight",
        lambda *_args: (_ for _ in ()).throw(RecordSecurityError("tracked")),
    )
    report = run_preflight(
        1, "01", Auth(), config_path=config, roster_path=roster, rubrics_root=rubrics
    )
    assert any(item.code == "MANUAL_OVERRIDES_TRACKED" for item in report.items)


def test_preflight_blocks_invalid_manual_grade_adjustment(tmp_path: Path) -> None:
    config, roster, rubrics = inputs(tmp_path)
    adjustment_path = tmp_path / "data" / "manual_grade_adjustments.csv"
    adjustment_path.parent.mkdir()
    adjustment_path.write_text("section,week,student_id,score\n01,1,EXAMPLE001,1.0\n", encoding="utf-8")
    report = run_preflight(
        1,
        "01",
        Auth(),
        config_path=config,
        roster_path=roster,
        rubrics_root=rubrics,
        manual_adjustments_path=adjustment_path,
    )
    assert any(item.code == "MANUAL_ADJUSTMENTS_INVALID" for item in report.items)


def test_preflight_blocks_tracked_private_manual_grade_adjustment(
    monkeypatch, tmp_path: Path
) -> None:
    config, roster, rubrics = inputs(tmp_path)

    def reject_adjustment(path: Path) -> None:
        if path.name == "manual_grade_adjustments.csv":
            raise RecordSecurityError("tracked")

    monkeypatch.setattr(
        "github_lab_grader.preflight.RecordStore.private_file_preflight",
        lambda _store, path: reject_adjustment(path),
    )
    report = run_preflight(
        1, "01", Auth(), config_path=config, roster_path=roster, rubrics_root=rubrics
    )
    assert any(item.code == "MANUAL_ADJUSTMENTS_INVALID" for item in report.items)
