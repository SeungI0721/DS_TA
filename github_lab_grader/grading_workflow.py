"""Phase 4 grading과 Phase 5 persistence를 filesystem 세부사항 없이 연결한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .models import CourseConfig, GradeResult, Student, WeeklyRubric
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
) -> GradingWorkflowResult:
    """학생별 null/error를 보존하면서 section 결과 전체를 한 record로 만든다."""

    store.privacy_preflight(section, rubric.week)
    results: tuple[GradeResult, ...] = orchestrator.grade_section_week(
        students, section, rubric, next_rubric=next_rubric
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
