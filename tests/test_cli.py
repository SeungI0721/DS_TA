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


def test_validate_config_uses_local_runtime_file(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("main.load_global_config", lambda path: calls.append(path))
    assert main(["validate-config"]) == 0
    assert len(calls) == 1
    assert calls[0].as_posix() == "config.json"
