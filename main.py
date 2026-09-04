"""로컬 채점 도구의 CLI entry point."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from github_lab_grader.auth import default_auth_provider
from github_lab_grader.config_loader import (
    ConfigurationError,
    load_global_config,
    load_students,
    load_weekly_rubric,
)
from github_lab_grader.github_client import GitHubClient, GitHubClientSettings
from github_lab_grader.grading_workflow import grade_and_persist
from github_lab_grader.orchestrator import GradingOrchestrator
from github_lab_grader.record_store import RecordStore, RecordStoreError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="github-lab-grader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    grade = subparsers.add_parser("grade", help="Grade one week")
    grade.add_argument("--week", type=int, required=True)
    scope = grade.add_mutually_exclusive_group(required=True)
    scope.add_argument("--section")
    scope.add_argument("--all-sections", action="store_true")
    grade.add_argument("--regrade", action="store_true")
    grade.add_argument("--regrade-reason")
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
            if args.regrade_reason is not None and not args.regrade:
                parser.error("--regrade-reason requires --regrade")
            if args.force_early_grading:
                parser.error("--force-early-grading is not supported by the canonical record workflow")
            # private 입력과 출력 경로를 GitHub 요청보다 먼저 검증한다.
            course = load_global_config(Path("config.json"))
            students = load_students(Path("data/students.csv"))
            rubric = load_weekly_rubric(Path("rubrics") / f"week{args.week:02d}.json")
            next_path = Path("rubrics") / f"week{args.week + 1:02d}.json"
            next_rubric = load_weekly_rubric(next_path) if next_path.is_file() else None
            sections = course.sections if args.all_sections else (args.section,)
            store = RecordStore()
            for section in sections:
                store.privacy_preflight(section, args.week)

            request = course.github_request
            settings = GitHubClientSettings(
                api_version=course.github_api_version,
                connect_timeout_seconds=float(request.get("connect_timeout_seconds", 5.0)),
                read_timeout_seconds=float(request.get("read_timeout_seconds", 20.0)),
                max_retries=int(request.get("max_retries", 2)),
                retry_backoff_seconds=float(request.get("retry_backoff_seconds", 0.5)),
                max_retry_after_seconds=float(request.get("max_retry_after_seconds", 60.0)),
                rate_limit_warning_threshold=int(request.get("rate_limit_warning_threshold", 100)),
            )
            credential = default_auth_provider().get_credential()
            orchestrator = GradingOrchestrator(GitHubClient(settings, credential), course)
            for section in sections:
                recorded_at = datetime.now(UTC)
                workflow = grade_and_persist(
                    orchestrator, store, course, rubric, students, section,
                    recorded_at=recorded_at, next_rubric=next_rubric,
                    regrade=args.regrade, regrade_reason=args.regrade_reason,
                    dry_run=args.dry_run,
                )
                record = workflow.record
                action = "SAVED" if workflow.written else "DRY_RUN"
                summary = record["summary"]
                print(
                    f"{action} section={section} week={args.week} "
                    f"revision={record['record_revision']} total={summary['total_students']} "
                    f"null={summary['ungraded_or_null']} errors={summary['errors']}"
                )
            return 0
    except (ConfigurationError, RecordStoreError, ValueError) as exc:
        parser.error(str(exc))
    parser.error(f"{args.command!r} CLI record workflow is scheduled for a later phase")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
