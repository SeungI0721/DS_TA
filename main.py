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
from github_lab_grader.gradebook import build_all_section_gradebooks
from github_lab_grader.grading_workflow import grade_and_persist
from github_lab_grader.orchestrator import GradingOrchestrator
from github_lab_grader.record_store import RecordStore, RecordStoreError
from github_lab_grader.excel_report import ExcelReportWriter, ReportError
from github_lab_grader.preflight import missing_operator_confirmations, run_preflight
from github_lab_grader.dry_run_diagnostics import build_dry_run_diagnostics, format_dry_run_diagnostics
from github_lab_grader.manual_grade_adjustments import (
    ManualGradeAdjustmentError,
    apply_adjustments_to_weekly_records,
    apply_manual_grade_adjustments,
    load_manual_grade_adjustments,
)


def _display_path(path: Path) -> str:
    """CLI에는 project-relative output 경로만 표시한다."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


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
    grade.add_argument("--details", action="store_true", help="List unresolved student IDs during dry-run")

    preflight = subparsers.add_parser("preflight", help="Validate real-course readiness without grading")
    preflight.add_argument("--week", type=int, required=True)
    preflight.add_argument("--section", required=True)

    week_report = subparsers.add_parser("week-report", help="Create weekly reports from JSON records")
    week_report.add_argument("--week", type=int, required=True)
    week_scope = week_report.add_mutually_exclusive_group()
    week_scope.add_argument("--section")
    week_scope.add_argument("--all-sections", action="store_true")

    rebuild = subparsers.add_parser("rebuild-gradebook", help="Rebuild workbooks from JSON records")
    rebuild.set_defaults(all_sections=True)
    subparsers.add_parser("final-report", help="Create the all-sections workbook")
    subparsers.add_parser("validate-config", help="Validate configuration without grading")
    subparsers.add_parser("validate-adjustments", help="Validate private manual grade adjustments")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            report = run_preflight(args.week, args.section, default_auth_provider())
            for item in report.items:
                print(f"{item.severity.value} {item.code}: {item.message}")
            print(f"PREFLIGHT_{'READY' if report.ready else 'BLOCKED'} section={args.section} week={args.week}")
            return 0 if report.ready else 1
        if args.command == "validate-config":
            load_global_config(Path("config.json"))
            for rubric_path in sorted(Path("rubrics").glob("week*.json")):
                load_weekly_rubric(rubric_path)
            return 0
        if args.command == "validate-adjustments":
            course = load_global_config(Path("config.json"))
            students = load_students(Path("data/students.csv"), configured_sections=course.sections)
            rubrics = {
                item.week: item
                for item in (load_weekly_rubric(path) for path in sorted(Path("rubrics").glob("week*.json")))
            }
            RecordStore().private_file_preflight(Path("data/manual_grade_adjustments.csv"))
            adjustments = load_manual_grade_adjustments(
                Path("data/manual_grade_adjustments.csv"), course, students, rubrics
            )
            print(f"MANUAL_ADJUSTMENTS_VALID count={len(adjustments)}")
            return 0
        if args.command in {"week-report", "rebuild-gradebook", "final-report"}:
            # 보고 명령은 canonical/local 입력만 읽으며 인증 provider나 GitHub client를 만들지 않는다.
            course = load_global_config(Path("config.json"))
            students = load_students(Path("data/students.csv"), configured_sections=course.sections)
            rubrics = {
                item.week: item
                for item in (
                    load_weekly_rubric(path)
                    for path in sorted(Path("rubrics").glob("week*.json"))
                )
            }
            store = RecordStore()
            writer = ExcelReportWriter()
            adjustment_path = Path("data/manual_grade_adjustments.csv")
            store.private_file_preflight(adjustment_path)
            adjustments = load_manual_grade_adjustments(
                adjustment_path, course, students, rubrics
            )
            if args.command == "week-report":
                sections = (args.section,) if args.section else course.sections
                unknown = tuple(section for section in sections if section not in course.sections)
                if unknown:
                    parser.error("section is not configured")
                records = [store.load(section, args.week) for section in sections]
                rubric = rubrics.get(args.week)
                if rubric is None:
                    parser.error("weekly rubric is not configured")
                path = writer.write_weekly_report(
                    apply_adjustments_to_weekly_records(records, adjustments), rubric
                )
                print(f"WEEK_REPORT_CREATED week={args.week} path={_display_path(path)}")
                return 0
            records = store.list_records()
            gradebooks = apply_manual_grade_adjustments(
                build_all_section_gradebooks(course, records, rubrics, students), adjustments
            )
            if args.command == "rebuild-gradebook":
                path = writer.write_final_report(gradebooks)
                print(f"GRADEBOOK_REBUILT path={_display_path(path)}")
                return 0
            path = writer.write_final_report(gradebooks)
            incomplete = sum(
                row.final_weighted_score is None for item in gradebooks for row in item.rows
            )
            print(f"FINAL_REPORT_CREATED path={_display_path(path)} incomplete={incomplete}")
            return 0
        if args.command == "grade":
            if args.details and not args.dry_run:
                parser.error("--details requires --dry-run")
            if args.regrade_reason is not None and not args.regrade:
                parser.error("--regrade-reason requires --regrade")
            if args.force_early_grading:
                parser.error("--force-early-grading is not supported by the canonical record workflow")
            # private 입력과 출력 경로를 GitHub 요청보다 먼저 검증한다.
            course = load_global_config(Path("config.json"))
            students = load_students(Path("data/students.csv"), configured_sections=course.sections)
            rubric = load_weekly_rubric(Path("rubrics") / f"week{args.week:02d}.json")
            if not args.dry_run and missing_operator_confirmations(course, rubric):
                parser.error(
                    "required private operator confirmations are incomplete; "
                    "run preflight before production grading"
                )
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
                if args.dry_run:
                    diagnostics = build_dry_run_diagnostics(
                        record,
                        settle_delay_hours=course.github_event_settle_delay_hours,
                        current_time=recorded_at,
                    )
                    for line in format_dry_run_diagnostics(diagnostics, details=args.details):
                        print(line)
            return 0
    except (ConfigurationError, ManualGradeAdjustmentError, RecordStoreError, ReportError, ValueError) as exc:
        parser.error(str(exc))
    parser.error(f"{args.command!r} CLI record workflow is scheduled for a later phase")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
