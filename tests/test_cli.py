from types import SimpleNamespace

import pytest

from main import build_parser, main


def test_grade_cli_preserves_section_as_text() -> None:
    args = build_parser().parse_args(["grade", "--week", "1", "--section", "01", "--regrade", "--regrade-reason", "재검토"])
    assert args.week == 1
    assert args.section == "01"
    assert args.regrade is True and args.regrade_reason == "재검토"


def test_grade_cli_requires_exactly_one_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["grade", "--week", "1"])


def test_force_early_grading_is_not_silently_ignored(monkeypatch) -> None:
    monkeypatch.setattr("main.load_global_config", lambda path: pytest.fail("must stop before I/O"))
    with pytest.raises(SystemExit):
        main(["grade", "--week", "1", "--section", "01", "--force-early-grading"])


def test_grade_details_requires_dry_run(monkeypatch) -> None:
    monkeypatch.setattr("main.load_global_config", lambda path: pytest.fail("must stop before I/O"))
    with pytest.raises(SystemExit):
        main(["grade", "--week", "1", "--section", "01", "--details"])


def test_production_grade_requires_operator_confirmation(monkeypatch, tmp_path) -> None:
    course = SimpleNamespace(
        sections=("01",), operator_confirmations=(), github_request={},
        github_api_version="2026-03-10",
    )
    rubric = SimpleNamespace(
        grading=SimpleNamespace(
            required_operator_confirmations=("professor_github_identity",)
        )
    )
    monkeypatch.setattr("main.load_global_config", lambda _path: course)
    monkeypatch.setattr("main.load_students", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("main.load_weekly_rubric", lambda _path: rubric)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["grade", "--week", "1", "--section", "01"])


def test_validate_config_uses_local_runtime_file(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("main.load_global_config", lambda path: calls.append(path))
    assert main(["validate-config"]) == 0
    assert len(calls) == 1
    assert calls[0].as_posix() == "config.json"


def test_report_cli_never_initializes_github(monkeypatch, tmp_path) -> None:
    class Store:
        def private_file_preflight(self, path):
            return None

        def load(self, section, week):
            return {"section": section, "week": week, "students": []}

    class Writer:
        def write_weekly_report(self, records, rubric):
            assert [record["section"] for record in records] == ["01"]
            return tmp_path / "week01_results.xlsx"

    course = type("Course", (), {"sections": ("01",)})()
    monkeypatch.setattr("main.load_global_config", lambda path: course)
    monkeypatch.setattr("main.load_students", lambda path, **kwargs: [])
    monkeypatch.setattr("main.load_weekly_rubric", lambda path: type("Rubric", (), {"week": 1})())
    monkeypatch.setattr("main.RecordStore", Store)
    monkeypatch.setattr("main.ExcelReportWriter", Writer)
    monkeypatch.setattr("main.default_auth_provider", lambda: pytest.fail("reporting must not authenticate"))
    assert main(["week-report", "--week", "1", "--section", "01"]) == 0


def test_report_cli_scopes_are_explicit() -> None:
    parser = build_parser()
    assert parser.parse_args(["rebuild-gradebook"]).all_sections
    args = parser.parse_args(["week-report", "--week", "1"])
    assert args.section is None and not args.all_sections
