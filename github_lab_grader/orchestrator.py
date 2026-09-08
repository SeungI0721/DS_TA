"""GitHub evidence를 학생별 GradeResult로 연결하는 Phase 4 orchestration 계층."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .grader import decide_grade
from .github_client import GitHubApiError
from .models import (
    CollaboratorCheckResult,
    CollaboratorStatus,
    CommitHistoryResult,
    CourseConfig,
    GradeResult,
    GradingStatus,
    LateWindowSource,
    ReadmeAtSha,
    ReadmeStatus,
    RepositoryEventsResult,
    RepositoryMetadata,
    ResolvedSectionDeadline,
    Student,
    SubmissionDecision,
    SubmissionEvidenceSource,
    SubmissionEvidenceType,
    SubmissionStatus,
    SubmissionTimestampType,
    WeeklyRubric,
)
from .readme_checker import check_readme_identity
from .submission_checker import (
    resolve_section_deadline,
    resolve_submission_branch,
    select_submission,
)


class GitHubEvidenceClient(Protocol):
    def get_repository(self, repository: str) -> RepositoryMetadata: ...

    def list_repository_events(self, repository: str) -> RepositoryEventsResult: ...

    def list_repository_commits(
        self, repository: str, branch: str, deadline: datetime
    ) -> CommitHistoryResult: ...

    def check_collaborator(
        self,
        repository: str,
        username: str,
        *,
        repository_accessible: bool,
        caller_has_push: bool | None,
    ) -> CollaboratorCheckResult: ...

    def get_readme_at_sha(self, repository: str, sha: str) -> ReadmeAtSha: ...


class GradingOrchestrator:
    """명시적 client와 clock을 사용해 한 학생 또는 한 section/week를 채점한다."""

    def __init__(
        self,
        github: GitHubEvidenceClient,
        course: CourseConfig,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.github = github
        self.course = course
        self.now = now

    def grade_student(
        self,
        student: Student,
        rubric: WeeklyRubric,
        *,
        next_rubric: WeeklyRubric | None = None,
    ) -> GradeResult:
        """학생 한 명의 오류를 structured result로 격리해 메모리에서 반환한다."""

        graded_at = self.now()
        if graded_at.tzinfo is None or graded_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        if student.section not in self.course.sections or rubric.week > self.course.total_weeks:
            return self._configuration_failure(student, rubric, graded_at, "unknown section or week")
        try:
            timing = resolve_section_deadline(rubric, student.section, next_rubric)
        except ValueError as exc:
            return self._configuration_failure(student, rubric, graded_at, str(exc))
        if rubric.grading.use_late_window and timing.late_window_end is None:
            return self._result(
                student,
                rubric,
                graded_at,
                timing,
                SubmissionDecision(
                    SubmissionStatus.CONFIGURATION_ERROR,
                    evidence_complete=False,
                    reason="final week requires an explicit late_window_end",
                ),
                decision_status=GradingStatus.MANUAL_REVIEW,
                manual_reason="final week requires an explicit late_window_end",
            )
        if not student.github_id or not student.repository:
            return self._result(
                student,
                rubric,
                graded_at,
                timing,
                SubmissionDecision(
                    SubmissionStatus.MISSING_REPOSITORY_INFO,
                    evidence_complete=False,
                    reason="GitHub submission information has not been registered",
                ),
                decision_status=GradingStatus.MANUAL_REVIEW,
                manual_reason="GitHub submission information has not been registered",
                error_code="MISSING_REPOSITORY_INFO",
            )
        settle_delay = timedelta(hours=self.course.github_event_settle_delay_hours)
        if graded_at < timing.effective_deadline + settle_delay:
            return self._result(
                student,
                rubric,
                graded_at,
                timing,
                SubmissionDecision(
                    SubmissionStatus.EVIDENCE_NOT_SETTLED,
                    evidence_complete=False,
                    reason="GitHub Events settle delay has not elapsed",
                ),
                decision_status=GradingStatus.MANUAL_REVIEW,
                manual_reason="GitHub Events settle delay has not elapsed",
            )

        fallback_readme: ReadmeAtSha | None = None
        try:
            metadata = self.github.get_repository(student.repository)
            branch = resolve_submission_branch(rubric.submission_branch, metadata.default_branch)
            events = self.github.list_repository_events(student.repository)
        except (GitHubApiError, ValueError) as exc:
            return self._api_failure(student, rubric, graded_at, timing, exc)

        submission = select_submission(
            events,
            student,
            branch,
            timing,
            graded_at,
            settle_delay=settle_delay,
            history_max_age=timedelta(days=self.course.github_event_history_max_age_days),
            require_actor=rubric.require_student_push_actor,
            use_late_window=rubric.grading.use_late_window,
            enforce_submission_window_start=rubric.grading.enforce_submission_window_start,
            enforce_submission_branch=rubric.grading.enforce_submission_branch,
        )
        if (
            submission.selected_sha is None
            and SubmissionEvidenceType.COMMIT_HISTORY
            in rubric.grading.submission_evidence_sources
            and submission.status not in {SubmissionStatus.AMBIGUOUS_SUBMISSION}
        ):
            try:
                history = self.github.list_repository_commits(
                    student.repository, branch, timing.effective_deadline
                )
                candidates = sorted(
                    (
                        commit
                        for commit in history.commits
                        if commit.committer_date <= timing.effective_deadline
                        and (
                            not rubric.grading.enforce_submission_window_start
                            or commit.committer_date >= timing.submission_window_start
                        )
                    ),
                    key=lambda commit: (commit.committer_date, commit.sha),
                    reverse=True,
                )
                for commit in candidates:
                    candidate_readme = self.github.get_readme_at_sha(
                        student.repository, commit.sha
                    )
                    if candidate_readme.exists:
                        fallback_readme = candidate_readme
                        submission = SubmissionDecision(
                            SubmissionStatus.ON_TIME,
                            evidence_source=SubmissionEvidenceSource.COMMIT_HISTORY_CONFIRMED,
                            selected_sha=commit.sha,
                            selected_timestamp=commit.committer_date,
                            timestamp_type=SubmissionTimestampType.COMMIT_COMMITTER_DATE,
                        )
                        break
                else:
                    if history.coverage_complete:
                        if candidates:
                            latest = candidates[0]
                            fallback_readme = ReadmeAtSha(False, latest.sha)
                            submission = SubmissionDecision(
                                SubmissionStatus.ON_TIME,
                                evidence_source=SubmissionEvidenceSource.COMMIT_HISTORY_CONFIRMED,
                                selected_sha=latest.sha,
                                selected_timestamp=latest.committer_date,
                                timestamp_type=SubmissionTimestampType.COMMIT_COMMITTER_DATE,
                            )
                        else:
                            after_deadline = tuple(
                                commit
                                for commit in history.commits
                                if commit.committer_date > timing.effective_deadline
                            )
                            submission = SubmissionDecision(
                                SubmissionStatus.LATE
                                if after_deadline
                                else SubmissionStatus.NOT_SUBMITTED,
                                reason=(
                                    "NO_TIMELY_SUBMISSION"
                                    if after_deadline
                                    else "EMPTY_REPOSITORY"
                                ),
                            )
                    else:
                        submission = SubmissionDecision(
                            SubmissionStatus.UNVERIFIABLE,
                            evidence_complete=False,
                            reason="commit history is insufficient",
                        )
            except (GitHubApiError, ValueError) as exc:
                return self._api_failure(student, rubric, graded_at, timing, exc)
        base_evidence = {
            "repository_id": metadata.repository_id,
            "submission_branch": branch,
            "submission_branch_enforced": rubric.grading.enforce_submission_branch,
            "settle_delay_hours": self.course.github_event_settle_delay_hours,
            "history_max_age_days": self.course.github_event_history_max_age_days,
        }
        if submission.status not in {
            SubmissionStatus.ON_TIME,
            SubmissionStatus.EXTENDED_ON_TIME,
        }:
            decision = decide_grade(
                submission.status,
                CollaboratorStatus.UNKNOWN,
                CollaboratorStatus.UNKNOWN,
                ReadmeStatus.NOT_CHECKED,
                rubric.score_rules,
                rubric.grading,
            )
            return self._result(
                student,
                rubric,
                graded_at,
                timing,
                submission,
                metadata=metadata,
                events=events,
                decision_status=decision.grading_status,
                score=decision.score,
                manual_reason=submission.reason or decision.manual_review_reason,
                evidence=base_evidence,
            )

        push_permission = metadata.permissions.get("push") if metadata.permissions else None
        professor: CollaboratorCheckResult | None = None
        assistant: CollaboratorCheckResult | None = None
        try:
            if rubric.grading.professor_collaborator_required:
                professor = self.github.check_collaborator(
                    student.repository,
                    self.course.professor_github,
                    repository_accessible=metadata.accessible,
                    caller_has_push=push_permission,
                )
            if rubric.grading.assistant_collaborator_required:
                assistant = self.github.check_collaborator(
                    student.repository,
                    self.course.assistant_github,
                    repository_accessible=metadata.accessible,
                    caller_has_push=push_permission,
                )
        except (GitHubApiError, ValueError) as exc:
            return self._api_failure(
                student, rubric, graded_at, timing, exc, submission=submission, metadata=metadata
            )

        readme_status = ReadmeStatus.NOT_CHECKED
        readme: ReadmeAtSha | None = fallback_readme
        student_id_found: bool | None = None
        student_name_found: bool | None = None
        error_code: str | None = None
        required_collaborators = tuple(
            result
            for result, required in (
                (professor, rubric.grading.professor_collaborator_required),
                (assistant, rubric.grading.assistant_collaborator_required),
            )
            if required
        )
        if rubric.grading.readme_required and all(
            result is not None and result.status is CollaboratorStatus.ACTIVE
            for result in required_collaborators
        ):
            try:
                selected_sha = submission.selected_sha
                assert selected_sha is not None
                if readme is None:
                    readme = self.github.get_readme_at_sha(student.repository, selected_sha)
                if not readme.exists:
                    readme_status = ReadmeStatus.MISSING
                elif readme.text is None:
                    readme_status = ReadmeStatus.UNVERIFIABLE
                elif not (
                    rubric.grading.student_id_required
                    or rubric.grading.student_name_required
                ):
                    readme_status = ReadmeStatus.COMPLETE
                else:
                    identity = check_readme_identity(readme.text, student)
                    student_id_found = identity.student_id_found
                    student_name_found = identity.student_name_found
                    required_identity_matches = (
                        not rubric.grading.student_id_required or student_id_found
                    ) and (
                        not rubric.grading.student_name_required or student_name_found
                    )
                    readme_status = (
                        ReadmeStatus.COMPLETE
                        if required_identity_matches
                        else ReadmeStatus.INCOMPLETE
                    )
            except GitHubApiError as exc:
                error_code = exc.code.value
                readme_status = (
                    ReadmeStatus.UNVERIFIABLE
                    if exc.code.value == "UNRESOLVABLE_REF"
                    else ReadmeStatus.ERROR
                )

        decision = decide_grade(
            submission.status,
            professor.status if professor else CollaboratorStatus.UNKNOWN,
            assistant.status if assistant else CollaboratorStatus.UNKNOWN,
            readme_status,
            rubric.score_rules,
            rubric.grading,
        )
        collaborator_error = (
            (professor.error_code if professor else None)
            or (assistant.error_code if assistant else None)
        )
        return self._result(
            student,
            rubric,
            graded_at,
            timing,
            submission,
            metadata=metadata,
            events=events,
            professor=professor,
            assistant=assistant,
            readme=readme,
            readme_status=readme_status,
            student_id_found=student_id_found,
            student_name_found=student_name_found,
            decision_status=decision.grading_status,
            score=decision.score,
            manual_reason=decision.manual_review_reason,
            error_code=error_code or (collaborator_error.value if collaborator_error else None),
            evidence={
                **base_evidence,
                "professor_collaborator_note": professor.note if professor else None,
                "assistant_collaborator_note": assistant.note if assistant else None,
            },
        )

    def grade_section_week(
        self,
        students: Iterable[Student],
        section: str,
        rubric: WeeklyRubric,
        *,
        next_rubric: WeeklyRubric | None = None,
    ) -> tuple[GradeResult, ...]:
        """대상 section의 각 학생을 독립적으로 처리해 한 오류의 전파를 막는다."""

        results: list[GradeResult] = []
        for student in students:
            if student.section != section:
                continue
            try:
                result = self.grade_student(student, rubric, next_rubric=next_rubric)
            except Exception as exc:  # 학생 단위 격리 경계에서는 예상 밖 오류도 결과로 보존한다.
                result = self._configuration_failure(
                    student,
                    rubric,
                    self.now(),
                    f"unexpected student-level error: {type(exc).__name__}",
                    grading_status=GradingStatus.ERROR,
                )
            results.append(result)
        return tuple(results)

    def _configuration_failure(
        self,
        student: Student,
        rubric: WeeklyRubric,
        graded_at: datetime,
        reason: str,
        *,
        grading_status: GradingStatus = GradingStatus.MANUAL_REVIEW,
    ) -> GradeResult:
        return self._result(
            student,
            rubric,
            graded_at,
            None,
            SubmissionDecision(
                SubmissionStatus.CONFIGURATION_ERROR,
                evidence_complete=False,
                reason=reason,
            ),
            decision_status=grading_status,
            manual_reason=reason,
            error_code="CONFIGURATION_ERROR",
        )

    def _api_failure(
        self,
        student: Student,
        rubric: WeeklyRubric,
        graded_at: datetime,
        timing: ResolvedSectionDeadline,
        exc: Exception,
        *,
        submission: SubmissionDecision | None = None,
        metadata: RepositoryMetadata | None = None,
    ) -> GradeResult:
        code = exc.code.value if isinstance(exc, GitHubApiError) else "CONFIGURATION_ERROR"
        return self._result(
            student,
            rubric,
            graded_at,
            timing,
            submission or SubmissionDecision(SubmissionStatus.ERROR, evidence_complete=False),
            metadata=metadata,
            decision_status=GradingStatus.ERROR,
            manual_reason="GitHub evidence could not be acquired reliably",
            error_code=code,
        )

    def _result(
        self,
        student: Student,
        rubric: WeeklyRubric,
        graded_at: datetime,
        timing: ResolvedSectionDeadline | None,
        submission: SubmissionDecision,
        *,
        metadata: RepositoryMetadata | None = None,
        events: RepositoryEventsResult | None = None,
        professor: CollaboratorCheckResult | None = None,
        assistant: CollaboratorCheckResult | None = None,
        readme: ReadmeAtSha | None = None,
        readme_status: ReadmeStatus = ReadmeStatus.NOT_CHECKED,
        student_id_found: bool | None = None,
        student_name_found: bool | None = None,
        decision_status: GradingStatus,
        score: float | None = None,
        manual_reason: str | None = None,
        error_code: str | None = None,
        evidence: dict[str, object] | None = None,
    ) -> GradeResult:
        push = submission.selected_push
        return GradeResult(
            semester=self.course.semester,
            course=self.course.course,
            section=student.section,
            week=rubric.week,
            student_id=student.student_id,
            name=student.name,
            github_id=student.github_id,
            repository=student.repository,
            repository_accessible=metadata.accessible if metadata else None,
            repository_default_branch=metadata.default_branch if metadata else None,
            submission_window_start=timing.submission_window_start if timing else None,
            scheduled_deadline=timing.scheduled_deadline if timing else None,
            effective_deadline=timing.effective_deadline if timing else None,
            late_window_end=timing.late_window_end if timing else None,
            late_window_source=(
                timing.late_window_source if timing else LateWindowSource.UNAVAILABLE
            ),
            deadline_note=timing.deadline_note if timing else "",
            submission_status=submission.status,
            submission_push_time=push.created_at if push else None,
            submission_push_actor=push.actor if push else None,
            submission_push_ref=push.ref if push else None,
            submission_push_head_sha=push.head_sha if push else None,
            submission_push_before_sha=push.before_sha if push else None,
            submission_push_event_id=push.event_id if push else None,
            professor_collaborator=(
                professor.status if professor else CollaboratorStatus.UNKNOWN
            ),
            assistant_collaborator=(
                assistant.status if assistant else CollaboratorStatus.UNKNOWN
            ),
            professor_collaborator_checked_at=professor.checked_at if professor else None,
            assistant_collaborator_checked_at=assistant.checked_at if assistant else None,
            readme_status=readme_status,
            readme_exists=readme.exists if readme else None,
            readme_path=readme.path if readme else None,
            student_id_found=student_id_found,
            student_name_found=student_name_found,
            score=score,
            max_score=rubric.max_score,
            grading_status=decision_status,
            manual_review_required=score is None,
            manual_review_reason=manual_reason,
            error_code=error_code,
            error_message=None,
            graded_at=graded_at,
            event_coverage=events.coverage if events else None,
            selected_push=push,
            evidence=dict(evidence or {}),
            submission_evidence_source=submission.evidence_source,
            selected_submission_sha=submission.selected_sha,
            selected_submission_timestamp=submission.selected_timestamp,
            selected_submission_timestamp_type=submission.timestamp_type,
        )
