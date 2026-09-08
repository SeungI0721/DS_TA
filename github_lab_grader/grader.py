"""정규화된 제출·collaborator·README 증거를 점수로 바꾸는 순수 계층."""

from __future__ import annotations

from .models import (
    CollaboratorStatus,
    GradeDecision,
    GradingStatus,
    GradingRules,
    ScoringMode,
    ReadmeStatus,
    ScoreRules,
    SubmissionStatus,
)


def decide_grade(
    submission_status: SubmissionStatus,
    professor_status: CollaboratorStatus,
    assistant_status: CollaboratorStatus,
    readme_status: ReadmeStatus,
    score_rules: ScoreRules,
    grading: GradingRules | None = None,
) -> GradeDecision:
    """신뢰 가능한 실패만 0점으로 하고 기술적 불확실성은 null로 보존한다."""

    if submission_status is SubmissionStatus.ERROR:
        return GradeDecision(GradingStatus.ERROR, None, "submission evidence acquisition failed")
    uncertain_submissions = {
        SubmissionStatus.EVIDENCE_NOT_SETTLED,
        SubmissionStatus.AMBIGUOUS_SUBMISSION,
        SubmissionStatus.CONFIGURATION_ERROR,
        SubmissionStatus.UNVERIFIABLE,
    }
    if submission_status in uncertain_submissions:
        return GradeDecision(
            GradingStatus.MANUAL_REVIEW,
            None,
            f"submission status is {submission_status.value}",
        )
    if submission_status in {SubmissionStatus.LATE, SubmissionStatus.NOT_SUBMITTED}:
        return GradeDecision(GradingStatus.FAIL, score_rules.fail)

    grading = grading or GradingRules()
    required_collaborators = []
    if grading.professor_collaborator_required:
        required_collaborators.append(professor_status)
    if grading.assistant_collaborator_required:
        required_collaborators.append(assistant_status)
    if CollaboratorStatus.ERROR in required_collaborators:
        return GradeDecision(GradingStatus.ERROR, None, "collaborator check failed")
    if CollaboratorStatus.UNKNOWN in required_collaborators:
        return GradeDecision(
            GradingStatus.MANUAL_REVIEW,
            None,
            "collaborator status is unknown",
        )
    if CollaboratorStatus.MISSING in required_collaborators:
        return GradeDecision(GradingStatus.FAIL, score_rules.fail)

    if not grading.readme_required:
        return GradeDecision(GradingStatus.PASS, score_rules.full)
    if readme_status is ReadmeStatus.MISSING:
        return GradeDecision(GradingStatus.FAIL, score_rules.fail)
    if readme_status is ReadmeStatus.ERROR:
        return GradeDecision(GradingStatus.ERROR, None, "README lookup failed")
    if readme_status in {ReadmeStatus.UNVERIFIABLE, ReadmeStatus.NOT_CHECKED}:
        return GradeDecision(
            GradingStatus.MANUAL_REVIEW,
            None,
            "README evidence is unavailable",
        )
    if readme_status is ReadmeStatus.COMPLETE:
        return GradeDecision(GradingStatus.PASS, score_rules.full)
    if grading.scoring_mode is ScoringMode.BINARY:
        return GradeDecision(GradingStatus.FAIL, score_rules.fail)
    return GradeDecision(GradingStatus.PARTIAL, score_rules.partial)
