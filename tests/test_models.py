from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from github_lab_grader.models import (
    CollaboratorStatus,
    LateWindowSource,
    SectionDeadline,
    Student,
    SubmissionStatus,
)


KST = timezone(timedelta(hours=9))


def test_section_identifier_preserves_leading_zero(fake_student: Student) -> None:
    assert fake_student.section == "01"


def test_section_deadline_supports_explicit_late_window() -> None:
    start = datetime(2026, 9, 1, tzinfo=KST)
    scheduled = datetime(2026, 9, 2, 23, 59, 59, tzinfo=KST)
    effective = datetime(2026, 9, 3, 23, 59, 59, tzinfo=KST)
    late_end = datetime(2026, 9, 8, 23, 59, 59, tzinfo=KST)
    timing = SectionDeadline(start, scheduled, effective, late_end)
    assert timing.late_window_end == late_end


def test_section_deadline_allows_deferred_late_window_resolution() -> None:
    start = datetime(2026, 9, 1, tzinfo=KST)
    deadline = datetime(2026, 9, 2, 23, 59, 59, tzinfo=KST)
    timing = SectionDeadline(start, deadline, deadline, None)
    assert timing.late_window_end is None


def test_required_status_values_are_stable_strings() -> None:
    assert SubmissionStatus.EXTENDED_ON_TIME == "EXTENDED_ON_TIME"
    assert CollaboratorStatus.UNKNOWN == "UNKNOWN"
    assert LateWindowSource.NEXT_WEEK_DERIVED == "NEXT_WEEK_DERIVED"


def test_section_deadline_rejects_naive_timestamps() -> None:
    naive = datetime(2026, 9, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        SectionDeadline(naive, naive, naive, None)


def test_section_deadline_rejects_invalid_order() -> None:
    start = datetime(2026, 9, 3, tzinfo=KST)
    scheduled = datetime(2026, 9, 2, tzinfo=KST)
    with pytest.raises(ValueError, match="submission_window_start"):
        SectionDeadline(start, scheduled, scheduled, None)

