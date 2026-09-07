"""Phase 6 테스트에서만 사용하는 fictional canonical record builder."""

from datetime import UTC, datetime, timedelta

from github_lab_grader.models import (
    CollaboratorStatus, CourseConfig, GradeResult, GradingRules, GradingStatus,
    LateWindowSource, ReadmeStatus, ScoreRules, SectionDeadline, Student,
    SubmissionStatus, WeeklyRubric,
)
from github_lab_grader.record_store import build_canonical_record

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def make_course(sections=("01",), weeks=3, weight=10.0):
    return CourseConfig(1, "2026-2", "Data Structures", "example-professor", "example-assistant", "Asia/Seoul", tuple(sections), weeks, weight, "2026-03-10", 6, 30, {})


def make_rubric(week, sections=("01",), maximum=1.0, future=False):
    start = NOW + timedelta(days=10) if future else NOW - timedelta(days=10)
    return WeeklyRubric(week, f"Week {week}", maximum, "main", True, {s: SectionDeadline(start, start + timedelta(days=1), start + timedelta(days=2), start + timedelta(days=3)) for s in sections}, GradingRules(), ScoreRules(maximum, maximum / 2, 0.0))


def make_student(student_id="EXAMPLE001", section="01", name="가상학생", github_id="student-example", repository="example/lab"):
    return Student(section, student_id, name, github_id, repository)


def make_result(student=None, week=1, score=1.0, maximum=1.0, grading=None, sha="a" * 40, reason=None):
    student = student or make_student()
    grading = grading or (GradingStatus.MANUAL_REVIEW if score is None else GradingStatus.FAIL if score == 0 else GradingStatus.PARTIAL if score < maximum else GradingStatus.PASS)
    submission = SubmissionStatus.UNVERIFIABLE if score is None else SubmissionStatus.LATE if score == 0 else SubmissionStatus.ON_TIME
    return GradeResult("2026-2", "Data Structures", student.section, week, student.student_id, student.name, student.github_id, student.repository, True, "main", NOW - timedelta(days=10), NOW - timedelta(days=9), NOW - timedelta(days=8), NOW - timedelta(days=7), LateWindowSource.EXPLICIT, "", submission, NOW - timedelta(days=9), student.github_id, "refs/heads/main", sha, "b" * 40, f"event-{week}", CollaboratorStatus.ACTIVE, CollaboratorStatus.ACTIVE, NOW, NOW, ReadmeStatus.COMPLETE, True, "README.md", True, True, score, maximum, grading, score is None, reason or ("확인 필요" if score is None else None), None, None, NOW)


def make_record(course, rubric, section="01", results=None, revision=1):
    values = results or [make_result(section_student, rubric.week, maximum=rubric.max_score) for section_student in [make_student(section=section)]]
    return build_canonical_record(course, rubric, section, values, recorded_at=NOW, record_revision=revision, previous_revision=revision - 1 if revision > 1 else None, regrade=revision > 1)
