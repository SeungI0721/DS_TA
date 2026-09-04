"""score와 불확실성 상태를 분리하는 pure decision 테스트."""

from github_lab_grader.grader import decide_grade
from github_lab_grader.models import (
    CollaboratorStatus,
    GradingStatus,
    ReadmeStatus,
    ScoreRules,
    SubmissionStatus,
)


SCORES = ScoreRules(1.0, 0.5, 0.0)


def decide(
    *,
    submission=SubmissionStatus.ON_TIME,
    professor=CollaboratorStatus.ACTIVE,
    assistant=CollaboratorStatus.ACTIVE,
    readme=ReadmeStatus.COMPLETE,
):
    return decide_grade(submission, professor, assistant, readme, SCORES)


def test_valid_submission_collaborators_and_identity_receive_full_score() -> None:
    result = decide()
    assert (result.grading_status, result.score) == (GradingStatus.PASS, 1.0)


def test_extended_submission_can_receive_full_score() -> None:
    assert decide(submission=SubmissionStatus.EXTENDED_ON_TIME).score == 1.0


def test_missing_one_identity_field_receives_partial_score() -> None:
    result = decide(readme=ReadmeStatus.INCOMPLETE)
    assert (result.grading_status, result.score) == (GradingStatus.PARTIAL, 0.5)


def test_missing_both_identity_fields_still_receives_partial_score() -> None:
    assert decide(readme=ReadmeStatus.INCOMPLETE).score == 0.5


def test_missing_readme_receives_zero() -> None:
    assert decide(readme=ReadmeStatus.MISSING).score == 0.0


def test_missing_professor_collaborator_receives_zero() -> None:
    assert decide(professor=CollaboratorStatus.MISSING).score == 0.0


def test_missing_assistant_collaborator_receives_zero() -> None:
    assert decide(assistant=CollaboratorStatus.MISSING).score == 0.0


def test_collaborator_uncertainty_requires_manual_review() -> None:
    result = decide(professor=CollaboratorStatus.UNKNOWN)
    assert result.grading_status is GradingStatus.MANUAL_REVIEW
    assert result.score is None


def test_collaborator_error_is_not_zero() -> None:
    result = decide(assistant=CollaboratorStatus.ERROR)
    assert result.grading_status is GradingStatus.ERROR
    assert result.score is None


def test_unverifiable_events_do_not_become_zero() -> None:
    result = decide(submission=SubmissionStatus.UNVERIFIABLE)
    assert result.grading_status is GradingStatus.MANUAL_REVIEW
    assert result.score is None


def test_late_and_reliable_not_submitted_are_zero() -> None:
    assert decide(submission=SubmissionStatus.LATE).score == 0.0
    assert decide(submission=SubmissionStatus.NOT_SUBMITTED).score == 0.0


def test_unavailable_readme_is_not_treated_as_missing() -> None:
    result = decide(readme=ReadmeStatus.UNVERIFIABLE)
    assert result.score is None
    assert result.grading_status is GradingStatus.MANUAL_REVIEW
