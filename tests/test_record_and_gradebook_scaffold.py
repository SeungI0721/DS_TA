"""gradebook acceptance 기준을 실제 Phase 6 구현에 연결한다."""

from github_lab_grader.gradebook import build_section_gradebook
from phase6_helpers import NOW, make_course, make_rubric, make_student


def test_ungraded_week_is_blank_not_zero() -> None:
    course = make_course(weeks=1)
    row = build_section_gradebook(
        course, "01", [], {1: make_rubric(1)}, [make_student()], as_of=NOW
    ).rows[0]
    assert row.weeks[0].score is None
