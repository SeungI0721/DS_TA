"""Phase 4 grading과 Phase 5 persistence를 filesystem 세부사항 없이 연결한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import CourseConfig, GradeResult, Student, WeeklyRubric
from .manual_overrides import apply_manual_overrides, load_manual_overrides
from .orchestrator import GradingOrchestrator
from .record_store import RecordStore, build_canonical_record


@dataclass(frozen=True, slots=True)
class GradingWorkflowResult:
    record: dict[str, object]
    written: bool


def grade_and_persist(
    orchestrator: GradingOrchestrator,
    store: RecordStore,
    course: CourseConfig,
    rubric: WeeklyRubric,
    students: Iterable[Student],
    section: str,
    *,
    recorded_at: datetime,
    next_rubric: WeeklyRubric | None = None,
    regrade: bool = False,
    regrade_reason: str | None = None,
    dry_run: bool = False,
    manual_overrides_path: Path | None = None,
) -> GradingWorkflowResult:
    """학생별 null/error를 보존하면서 section 결과 전체를 한 record로 만든다."""

    manual_overrides_path = manual_overrides_path or store.project_root / "data" / "manual_overrides.json"
    store.privacy_preflight(section, rubric.week)
    store.private_file_preflight(manual_overrides_path)
    results: tuple[GradeResult, ...] = orchestrator.grade_section_week(
        students, section, rubric, next_rubric=next_rubric
    )
    overrides = load_manual_overrides(manual_overrides_path)
    if regrade or dry_run:
        relevant = tuple(
            item
            for item in overrides
            if item.section == section and item.week == rubric.week
        )
        if relevant:
            results = apply_manual_overrides(
                results,
                overrides=relevant,
                previous_record=store.load(section, rubric.week),
                section=section,
                week=rubric.week,
            )
    if dry_run:
        record = build_canonical_record(
            course, rubric, section, results, recorded_at=recorded_at
        )
        return GradingWorkflowResult(record, False)
    record = store.save(
        course,
        rubric,
        section,
        results,
        recorded_at=recorded_at,
        regrade=regrade,
        regrade_reason=regrade_reason,
    )
    return GradingWorkflowResult(record, True)
