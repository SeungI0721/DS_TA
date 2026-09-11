"""실제 채점 전에 로컬 입력·시각·인증 상태를 읽기 전용으로 점검한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .auth import AuthProvider
from .config_loader import ConfigurationError, load_global_config, load_students, load_weekly_rubric
from .github_client import GitHubClientSettings
from .manual_overrides import ManualOverrideError, load_manual_overrides
from .manual_grade_adjustments import ManualGradeAdjustmentError, load_manual_grade_adjustments
from .record_store import RecordNotFoundError, RecordSecurityError, RecordStore, RecordStoreError
from .submission_checker import resolve_section_deadline


class PreflightSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class PreflightItem:
    severity: PreflightSeverity
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    items: tuple[PreflightItem, ...]
    section: str
    week: int

    @property
    def ready(self) -> bool:
        return not any(item.severity is PreflightSeverity.BLOCKER for item in self.items)


def _settings(config) -> GitHubClientSettings:
    request = config.github_request
    return GitHubClientSettings(
        api_version=config.github_api_version,
        connect_timeout_seconds=float(request.get("connect_timeout_seconds", 5.0)),
        read_timeout_seconds=float(request.get("read_timeout_seconds", 20.0)),
        max_retries=int(request.get("max_retries", 2)),
        retry_backoff_seconds=float(request.get("retry_backoff_seconds", 0.5)),
        max_retry_after_seconds=float(request.get("max_retry_after_seconds", 60.0)),
        rate_limit_warning_threshold=int(request.get("rate_limit_warning_threshold", 100)),
    )


def missing_operator_confirmations(config, rubric) -> tuple[str, ...]:
    """rubric이 요구하지만 private config에서 확인되지 않은 운영 항목을 반환한다."""

    return tuple(
        key
        for key in rubric.grading.required_operator_confirmations
        if key not in config.operator_confirmations
    )


def run_preflight(
    week: int,
    section: str,
    auth_provider: AuthProvider,
    *,
    config_path: Path = Path("config.json"),
    roster_path: Path = Path("data/students.csv"),
    rubrics_root: Path = Path("rubrics"),
    manual_overrides_path: Path | None = None,
    manual_adjustments_path: Path | None = None,
    now: datetime | None = None,
) -> PreflightReport:
    """어떤 canonical/output 파일도 만들지 않고 운영 가능 여부를 요약한다."""

    items: list[PreflightItem] = []
    manual_overrides_path = manual_overrides_path or config_path.parent / "data" / "manual_overrides.json"
    manual_adjustments_path = manual_adjustments_path or config_path.parent / "data" / "manual_grade_adjustments.csv"
    try:
        RecordStore().private_file_preflight(manual_overrides_path)
    except RecordSecurityError:
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDES_TRACKED", "private manual override file is Git-tracked"))
    if not config_path.is_file():
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "CONFIG_MISSING", "config.json 파일이 없습니다."))
    if not roster_path.is_file():
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "ROSTER_MISSING", "data/students.csv 파일이 없습니다."))
    if items:
        return PreflightReport(tuple(items), section, week)

    try:
        config = load_global_config(config_path)
        _settings(config)
    except (ConfigurationError, TypeError, ValueError) as exc:
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "CONFIG_INVALID", str(exc)))
        return PreflightReport(tuple(items), section, week)

    if section not in config.sections:
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "SECTION_UNKNOWN", "요청한 분반이 config.json에 없습니다."))

    rubric_path = rubrics_root / f"week{week:02d}.json"
    if not rubric_path.is_file():
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "RUBRIC_MISSING", "요청한 주차 rubric 파일이 없습니다."))
        rubric = None
    else:
        try:
            rubric = load_weekly_rubric(rubric_path)
        except ConfigurationError as exc:
            items.append(PreflightItem(PreflightSeverity.BLOCKER, "RUBRIC_INVALID", str(exc)))
            rubric = None

    try:
        students = load_students(roster_path, configured_sections=config.sections)
    except ConfigurationError as exc:
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "ROSTER_INVALID", str(exc)))
        students = []

    try:
        RecordStore().private_file_preflight(manual_adjustments_path)
        adjustment_rubrics = {
            item.week: item
            for item in (
                load_weekly_rubric(path)
                for path in sorted(rubrics_root.glob("week*.json"))
            )
        }
        load_manual_grade_adjustments(
            manual_adjustments_path, config, students, adjustment_rubrics
        )
    except (ManualGradeAdjustmentError, RecordSecurityError):
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_ADJUSTMENTS_INVALID", "private manual grade adjustment file is invalid or Git-tracked"))

    try:
        overrides = load_manual_overrides(manual_overrides_path)
    except ManualOverrideError:
        overrides = ()
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDES_INVALID", "private manual override file is invalid"))
    for override in overrides:
        if override.week != week or override.section != section:
            continue
        if not any(student.student_id == override.student_id for student in students):
            items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDE_STUDENT_MISSING", "manual override student is absent from current roster"))
            continue
        try:
            source = RecordStore().load(section, week)
            prior = next(
                student for student in source["students"]
                if student["student_id"] == override.student_id
            )
            if prior.get("score") is None:
                items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDE_SOURCE_UNRESOLVED", "manual override source result is not resolved"))
        except StopIteration:
            items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDE_SOURCE_STUDENT_MISSING", "manual override student is absent from previous canonical record"))
        except RecordNotFoundError:
            items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDE_SOURCE_MISSING", "manual override requires a previous canonical record"))
        except RecordStoreError:
            items.append(PreflightItem(PreflightSeverity.BLOCKER, "MANUAL_OVERRIDE_SOURCE_INVALID", "manual override source record is invalid"))

    section_students = [student for student in students if student.section == section]
    registered = sum(bool(student.github_id and student.repository) for student in section_students)
    missing = len(section_students) - registered
    items.append(PreflightItem(PreflightSeverity.INFO, "STUDENT_COUNT", f"분반 학생 수: {len(section_students)}"))
    items.append(PreflightItem(PreflightSeverity.INFO, "REGISTERED_COUNT", f"등록된 GitHub 저장소 수: {registered}"))
    if missing:
        items.append(PreflightItem(PreflightSeverity.WARNING, "MISSING_REPOSITORY_INFO", f"GitHub 등록 미완료 학생 수: {missing}; 해당 점수는 null로 유지됩니다."))

    if rubric is not None and section in config.sections:
        if section not in rubric.sections:
            items.append(PreflightItem(PreflightSeverity.BLOCKER, "RUBRIC_SECTION_MISSING", "rubric에 요청한 분반 시각 설정이 없습니다."))
        else:
            next_path = rubrics_root / f"week{week + 1:02d}.json"
            try:
                next_rubric = load_weekly_rubric(next_path) if next_path.is_file() else None
                timing = resolve_section_deadline(rubric, section, next_rubric)
                if rubric.grading.use_late_window and timing.late_window_end is None:
                    items.append(PreflightItem(PreflightSeverity.BLOCKER, "LATE_WINDOW_UNRESOLVED", "late_window_end를 결정할 수 없습니다."))
                else:
                    checked_at = now or datetime.now(UTC)
                    settled_at = timing.effective_deadline + timedelta(hours=config.github_event_settle_delay_hours)
                    items.append(PreflightItem(PreflightSeverity.INFO, "EFFECTIVE_DEADLINE", f"effective deadline: {timing.effective_deadline.isoformat()}"))
                    items.append(PreflightItem(PreflightSeverity.INFO, "DEADLINE_NOTE", timing.deadline_note))
                    items.append(PreflightItem(PreflightSeverity.INFO, "SCORING_MODE", f"scoring mode: {rubric.grading.scoring_mode.value}"))
                    items.append(PreflightItem(PreflightSeverity.INFO, "SETTLE_TIME", f"evidence settle time: {settled_at.isoformat()}"))
                    start_boundary = (
                        timing.submission_window_start.isoformat()
                        if rubric.grading.enforce_submission_window_start
                        else "NOT_ENFORCED"
                    )
                    items.append(PreflightItem(PreflightSeverity.INFO, "SUBMISSION_START_BOUNDARY", f"submission start boundary: {start_boundary}"))
                    branch_policy = (
                        f"ENFORCED:{rubric.submission_branch}"
                        if rubric.grading.enforce_submission_branch
                        else "NOT_ENFORCED (BRANCH_REFS_ONLY)"
                    )
                    items.append(PreflightItem(PreflightSeverity.INFO, "SUBMISSION_BRANCH_POLICY", f"submission branch policy: {branch_policy}"))
                    evidence_sources = ", ".join(
                        source.value for source in rubric.grading.submission_evidence_sources
                    )
                    items.append(PreflightItem(PreflightSeverity.INFO, "SUBMISSION_EVIDENCE_SOURCES", f"accepted evidence sources: {evidence_sources}"))
                    collaborator_roles = ", ".join(
                        role
                        for role, required in (
                            ("professor", rubric.grading.professor_collaborator_required),
                            ("assistant", rubric.grading.assistant_collaborator_required),
                        )
                        if required
                    )
                    items.append(PreflightItem(PreflightSeverity.INFO, "REQUIRED_COLLABORATORS", f"required collaborator roles: {collaborator_roles or 'none'}"))
                    path_policy = " AND ".join(
                        "(" + " OR ".join(group.paths) + ")"
                        for group in rubric.grading.required_path_groups
                    )
                    items.append(PreflightItem(PreflightSeverity.INFO, "REQUIRED_PATH_GROUPS", f"required deadline-bound paths: {path_policy or 'legacy rubric policy'}"))
                    missing_confirmations = missing_operator_confirmations(config, rubric)
                    if missing_confirmations:
                        items.append(PreflightItem(PreflightSeverity.BLOCKER, "OPERATOR_CONFIRMATION_REQUIRED", "required collaborator identity must be confirmed in private config before grading"))
                    elif rubric.grading.required_operator_confirmations:
                        items.append(PreflightItem(PreflightSeverity.INFO, "OPERATOR_CONFIRMATION_COMPLETE", "required private operator confirmations are complete"))
                    if checked_at < settled_at:
                        items.append(PreflightItem(PreflightSeverity.WARNING, "EVIDENCE_NOT_SETTLED", "GitHub Events settle 시간이 아직 지나지 않았습니다."))
                    if not rubric.grading.use_late_window:
                        items.append(PreflightItem(PreflightSeverity.INFO, "LATE_WINDOW_NOT_REQUIRED", "이 rubric은 effective deadline 이후 late-window 판정을 사용하지 않습니다."))
            except (ConfigurationError, ValueError) as exc:
                items.append(PreflightItem(PreflightSeverity.BLOCKER, "TIMING_INVALID", str(exc)))

    credential = auth_provider.get_credential()
    if credential is None:
        items.append(PreflightItem(PreflightSeverity.BLOCKER, "AUTH_UNAVAILABLE", "GitHub 인증 정보를 사용할 수 없습니다."))
    else:
        items.append(PreflightItem(PreflightSeverity.INFO, "AUTH_AVAILABLE", f"GitHub 인증 source: {credential.source.value}"))
    return PreflightReport(tuple(items), section, week)
