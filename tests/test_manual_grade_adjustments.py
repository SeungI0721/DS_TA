"""Private manual grade adjustment의 loader와 effective-grade projection 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from github_lab_grader.manual_grade_adjustments import (
    ManualGradeAdjustment,
    ManualGradeAdjustmentError,
    apply_adjustments_to_weekly_records,
    apply_manual_grade_adjustments,
    load_manual_grade_adjustments,
)
from github_lab_grader.models import GradingRules, ScoreRules, ScoringMode, WeeklyRubric
from github_lab_grader.gradebook import build_all_section_gradebooks
from phase6_helpers import NOW, make_course, make_record, make_result, make_rubric, make_student


def write_csv(path: Path, rows: str) -> None:
    path.write_text("section,week,student_id,score,reason\n" + rows, encoding="utf-8")


def inputs():
    course = make_course(weeks=2)
    students = [make_student("EXAMPLE001")]
    rubrics = {1: make_rubric(1), 2: make_rubric(2)}
    return course, students, rubrics


def test_absent_adjustment_file_is_empty_and_does_not_change_gradebook(tmp_path: Path) -> None:
    course, students, rubrics = inputs()
    assert load_manual_grade_adjustments(tmp_path / "missing.csv", course, students, rubrics) == ()
    records = [make_record(course, rubrics[1], results=[make_result(students[0], score=1.0)])]
    automatic = build_all_section_gradebooks(course, records, rubrics, students, as_of=NOW)
    assert apply_manual_grade_adjustments(automatic, ()) == automatic


@pytest.mark.parametrize(
    "rows",
    [
        "01,1,EXAMPLE001,0.5,duplicate one\n01,1,EXAMPLE001,1.0,duplicate two\n",
        "01,1,UNKNOWN,1.0,unknown student\n",
        "02,1,EXAMPLE001,1.0,wrong section\n",
        "01,9,EXAMPLE001,1.0,invalid week\n",
        "01,1,EXAMPLE001,nope,not numeric\n",
        "01,1,EXAMPLE001,2.0,out of range\n",
        "01,1,EXAMPLE001,1.0,\n",
    ],
)
def test_invalid_rows_are_rejected(tmp_path: Path, rows: str) -> None:
    course, students, rubrics = inputs(); path = tmp_path / "adjustments.csv"
    write_csv(path, rows)
    with pytest.raises(ManualGradeAdjustmentError):
        load_manual_grade_adjustments(path, course, students, rubrics)


def test_binary_week_rejects_half_but_partial_rubric_allows_it(tmp_path: Path) -> None:
    course, students, rubrics = inputs(); path = tmp_path / "adjustments.csv"
    base = rubrics[1]
    rubrics[1] = WeeklyRubric(
        base.week, base.title, base.max_score, base.submission_branch,
        base.require_student_push_actor, base.sections,
        GradingRules(scoring_mode=ScoringMode.BINARY), ScoreRules(1.0, 0.0, 0.0),
    )
    write_csv(path, "01,1,EXAMPLE001,0.5,not binary\n")
    with pytest.raises(ManualGradeAdjustmentError, match="not allowed"):
        load_manual_grade_adjustments(path, course, students, rubrics)
    partial = make_rubric(1)
    rubrics[1] = WeeklyRubric(
        partial.week, partial.title, partial.max_score, partial.submission_branch,
        partial.require_student_push_actor, partial.sections,
        GradingRules(), ScoreRules(1.0, 0.5, 0.0),
    )
    assert load_manual_grade_adjustments(path, course, students, rubrics)[0].score == 0.5


@pytest.mark.parametrize(
    ("automatic_score", "adjusted_score"),
    [(1.0, None), (0.0, 1.0), (None, 1.0), (1.0, 0.0), (None, None)],
)
def test_effective_score_uses_adjustment_only_when_present(automatic_score, adjusted_score) -> None:
    course, students, rubrics = inputs()
    records = [make_record(course, rubrics[1], results=[make_result(students[0], score=automatic_score)])]
    books = build_all_section_gradebooks(course, records, {1: rubrics[1]}, students, as_of=NOW)
    adjustments = () if adjusted_score is None else (
        ManualGradeAdjustment("01", 1, "EXAMPLE001", adjusted_score, "fictional approval"),
    )
    week = apply_manual_grade_adjustments(books, adjustments)[0].rows[0].weeks[0]
    assert week.score == (adjusted_score if adjusted_score is not None else automatic_score)
    assert week.automatic_score == automatic_score
    assert week.resolution_source == ("MANUAL_ADJUSTMENT" if adjusted_score is not None else "AUTOMATIC")


def test_adjustment_resolves_null_for_final_grade_and_weekly_projection() -> None:
    course = make_course(weeks=1)
    students = [make_student("EXAMPLE001")]
    rubrics = {1: make_rubric(1)}
    records = [make_record(course, rubrics[1], results=[make_result(students[0], score=None)])]
    adjustment = ManualGradeAdjustment("01", 1, "EXAMPLE001", 1.0, "fictional approval")
    book = apply_manual_grade_adjustments(
        build_all_section_gradebooks(course, records, {1: rubrics[1]}, students, as_of=NOW),
        (adjustment,),
    )[0]
    assert book.rows[0].weeks[0].score == 1.0
    assert book.rows[0].final_weighted_score == course.final_practice_weight
    projected = apply_adjustments_to_weekly_records(records, (adjustment,))
    student = projected[0]["students"][0]
    assert student["automatic_score"] is None
    assert student["manual_adjustment_score"] == 1.0
    assert student["effective_score"] == 1.0
