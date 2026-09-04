"""로컬 채점 도구의 CLI entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from github_lab_grader.config_loader import (
    ConfigurationError,
    load_global_config,
    load_weekly_rubric,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="github-lab-grader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    grade = subparsers.add_parser("grade", help="Grade one week")
    grade.add_argument("--week", type=int, required=True)
    scope = grade.add_mutually_exclusive_group(required=True)
    scope.add_argument("--section")
    scope.add_argument("--all-sections", action="store_true")
    grade.add_argument("--regrade", action="store_true")
    grade.add_argument("--dry-run", action="store_true")
    grade.add_argument("--force-early-grading", action="store_true")

    subparsers.add_parser("rebuild-gradebook", help="Rebuild workbooks from JSON records")
    subparsers.add_parser("final-report", help="Create the all-sections workbook")
    subparsers.add_parser("validate-config", help="Validate configuration without grading")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-config":
            load_global_config(Path("config.json"))
            for rubric_path in sorted(Path("rubrics").glob("week*.json")):
                load_weekly_rubric(rubric_path)
            return 0
        if args.command == "grade":
            # 실제 학생을 읽기 전에 private runtime config의 Git 추적 여부부터 확인한다.
            load_global_config(Path("config.json"))
    except ConfigurationError as exc:
        parser.error(str(exc))
    parser.error(f"{args.command!r} CLI record workflow is scheduled for a later phase")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
