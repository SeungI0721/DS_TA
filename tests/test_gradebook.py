"""canonical record 기반 gradebook reconstruction 테스트."""

from dataclasses import replace
from datetime import timedelta

import pytest

from github_lab_grader.gradebook import CompletionStatus, WeekReportStatus, build_all_section_gradebooks, build_section_gradebook
from github_lab_grader.models import GradingStatus
from phase6_helpers import NOW, make_course, make_record, make_result, make_rubric, make_student


def test_reconstructs_multiple_weeks_in_numeric_order_and_merges_student() -> None:
    course = make_course(weeks=10)
    rubrics = {week: make_rubric(week) for week in range(1, 11)}
    records = [make_record(course, rubrics[week]) for week in (10, 2, 1)]
    gradebook = build_section_gradebook(course, "01", records, rubrics)
    assert gradebook.expected_weeks == tuple(range(1, 11))
    assert len(gradebook.rows) == 1
    assert [item.week for item in gradebook.rows[0].weeks] == list(range(1, 11))
    assert gradebook.rows[0].weeks[9].submission_push_head_sha == "a" * 40


def test_roster_order_precedes_canonical_only_students_and_preserves_text_ids() -> None:
    course = make_course(weeks=1); rubric = make_rubric(1)
    roster = [make_student("0002", name="두번째"), make_student("0001", name="첫번째")]
    external = make_student("0003", name="기록학생")
    record = make_record(course, rubric, results=[make_result(roster[0]), make_result(roster[1]), make_result(external)])
    book = build_section_gradebook(course, "01", [record], {1: rubric}, roster)
    assert [row.student_id for row in book.rows] == ["0002", "0001", "0003"]
    assert book.rows[0].section == "01" and book.rows[0].name == "두번째"
    assert any(issue.code == "CANONICAL_STUDENT_NOT_IN_ROSTER" for issue in book.issues)


@pytest.mark.parametrize(("field", "value"), [("name", "다른이름"), ("github_id", "other-user"), ("repository", "other/repo")])
def test_cross_week_identity_mismatch_is_explicit(field: str, value: str) -> None:
    course = make_course(weeks=2); rubrics = {1: make_rubric(1), 2: make_rubric(2)}
    first = make_student(); second = replace(first, **{field: value})
    records = [make_record(course, rubrics[1], results=[make_result(first, 1)]), make_record(course, rubrics[2], results=[make_result(second, 2)])]
    book = build_section_gradebook(course, "01", records, rubrics)
    assert any(issue.code == "IDENTITY_MISMATCH" and issue.field == field for issue in book.issues)
    assert book.rows[0].completion_status is CompletionStatus.REVIEW_REQUIRED


def test_roster_student_without_record_has_blank_missing_and_future_weeks() -> None:
    course = make_course(weeks=2); roster = [make_student()]
    rubrics = {1: make_rubric(1), 2: make_rubric(2, future=True)}
    row = build_section_gradebook(course, "01", [], rubrics, roster, as_of=NOW).rows[0]
    assert row.weeks[0].score is None and row.weeks[0].report_status is WeekReportStatus.RECORD_MISSING
    assert row.weeks[1].score is None and row.weeks[1].report_status is WeekReportStatus.FUTURE_WEEK
    assert row.final_weighted_score is None


def test_score_semantics_totals_and_weight_use_actual_maxima() -> None:
    course = make_course(weeks=3, weight=10.0)
    rubrics = {1: make_rubric(1, maximum=1.0), 2: make_rubric(2, maximum=2.0), 3: make_rubric(3, maximum=3.0)}
    scores = (1.0, 0.0, 1.5)
    records = [make_record(course, rubrics[w], results=[make_result(week=w, score=scores[w-1], maximum=rubrics[w].max_score)]) for w in rubrics]
    row = build_section_gradebook(course, "01", records, rubrics).rows[0]
    assert [week.score for week in row.weeks] == [1.0, 0.0, 1.5]
    assert row.earned_score == 2.5 and row.resolved_possible_score == 6.0
    assert row.configured_possible_score == 6.0
    assert row.final_weighted_score == pytest.approx(2.5 / 6.0 * 10.0)
    assert row.completion_status is CompletionStatus.COMPLETE


@pytest.mark.parametrize("kind", ["null", "missing", "manual", "error"])
def test_unresolved_required_week_never_gets_final_score(kind: str) -> None:
    course = make_course(weeks=2); rubrics = {1: make_rubric(1), 2: make_rubric(2)}
    records = [make_record(course, rubrics[1])]
    if kind != "missing":
        grading = GradingStatus.ERROR if kind == "error" else GradingStatus.MANUAL_REVIEW
        records.append(make_record(course, rubrics[2], results=[make_result(week=2, score=None, grading=grading)]))
    row = build_section_gradebook(course, "01", records, rubrics).rows[0]
    assert row.final_weighted_score is None and row.completion_status is not CompletionStatus.COMPLETE
    assert row.resolved_possible_score == 1.0


def test_canonical_max_mismatch_is_flagged_without_rewriting_history() -> None:
    course = make_course(weeks=1); rubric = make_rubric(1, maximum=2.0)
    record = make_record(course, rubric, results=[make_result(maximum=1.0)])
    book = build_section_gradebook(course, "01", [record], {1: rubric})
    assert book.rows[0].weeks[0].max_score == 1.0
    assert book.issues[0].code == "MAX_SCORE_MISMATCH"
    assert book.rows[0].final_weighted_score is None


def test_arbitrary_sections_use_natural_order() -> None:
    course = make_course(("10", "02", "01"), weeks=1)
    rubrics = {1: make_rubric(1, sections=course.sections)}
    books = build_all_section_gradebooks(course, [], rubrics, [make_student(section=s) for s in course.sections])
    assert [book.section for book in books] == ["01", "02", "10"]


def test_out_of_range_rubric_cannot_hide_required_week_gap() -> None:
    course = make_course(weeks=2)
    rubrics = {1: make_rubric(1), 3: make_rubric(3)}
    record = make_record(course, rubrics[1])
    row = build_section_gradebook(course, "01", [record], rubrics).rows[0]
    assert row.final_weighted_score is None
