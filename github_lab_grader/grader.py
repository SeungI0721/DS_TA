"""정규화된 제출·collaborator·README 증거를 점수로 바꾸는 순수 계층."""

from __future__ import annotations

from .models import (
    CollaboratorStatus,
    GradeDecision,
    GradingStatus,
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

    if CollaboratorStatus.ERROR in {professor_status, assistant_status}:
        return GradeDecision(GradingStatus.ERROR, None, "collaborator check failed")
    if CollaboratorStatus.UNKNOWN in {professor_status, assistant_status}:
        return GradeDecision(
            GradingStatus.MANUAL_REVIEW,
            None,
            "collaborator status is unknown",
        )
    if CollaboratorStatus.MISSING in {professor_status, assistant_status}:
        return GradeDecision(GradingStatus.FAIL, score_rules.fail)

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
    return GradeDecision(GradingStatus.PARTIAL, score_rules.partial)
