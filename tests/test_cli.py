import pytest

from main import build_parser


def test_grade_cli_preserves_section_as_text() -> None:
    args = build_parser().parse_args(["grade", "--week", "1", "--section", "01"])
    assert args.week == 1
    assert args.section == "01"


def test_grade_cli_requires_exactly_one_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["grade", "--week", "1"])

