"""Self-contained Week 2 component rubric, oracle, snapshot 판정 회귀 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from github_lab_grader.c_checker import (
    CCompiler,
    CCompilerKind,
    ExecutionResult,
    ExecutionUnavailable,
    aggregate_component_results,
    array_statistics_match,
    check_c_submission,
    classify_practice7_source,
    discover_c_compiler,
    expected_array_statistics,
    expected_first_max_index,
    expected_first_min_index,
    expected_max,
    expected_min,
    expected_negative_count,
    expected_positive_sum_average,
    validate_checker_output,
)
from github_lab_grader.config_loader import load_weekly_rubric
from github_lab_grader.github_client import GitHubApiError
from github_lab_grader.models import (
    CCheckerId,
    CommitHistoryResult,
    CommitRecord,
    ComponentResult,
    ComponentStatus,
    CourseConfig,
    EventCoverage,
    GradingComponent,
    GitHubErrorCode,
    RepositoryEventsResult,
    RepositoryMetadata,
    RepositoryProjectSources,
    RepositorySourceFile,
    RepositorySourcesAtSha,
    Student,
)
from github_lab_grader.orchestrator import GradingOrchestrator
from github_lab_grader.submission_checker import resolve_section_deadline, select_submission

ROOT = Path(__file__).resolve().parents[1]
KST = datetime.fromisoformat("2026-09-09T23:59:00+09:00").tzinfo
RUBRIC = load_weekly_rubric(ROOT / "rubrics" / "week02.json")


def test_week02_mapping_and_policy_are_exact() -> None:
    assert [(item.project_path, item.practice_number, item.checker.value) for item in RUBRIC.components_by_section["01"]] == [
        ("week02-01", 1, "MAX_VALUE"),
        ("week02-02", 3, "NEGATIVE_COUNT"),
        ("week02-03", 5, "MAX_INDEX_FIRST"),
        ("week02-04", 7, "ARRAY_COMPARE_MAE"),
    ]
    assert [item.practice_number for item in RUBRIC.components_by_section["02"]] == [2, 4, 6, 7]
    assert all(item.max_score == 0.25 for values in RUBRIC.components_by_section.values() for item in values)
    assert not RUBRIC.grading.readme_required
    assert not RUBRIC.grading.professor_collaborator_required
    assert not RUBRIC.grading.assistant_collaborator_required
    assert not RUBRIC.grading.enforce_submission_branch
    assert not RUBRIC.grading.enforce_submission_window_start
    assert not RUBRIC.grading.use_late_window


@pytest.mark.parametrize(("passes", "expected"), [(4, 1.0), (3, 0.75), (2, 0.5), (1, 0.25), (0, 0.0)])
def test_component_sum_score_lattice(passes: int, expected: float) -> None:
    values = tuple(
        ComponentResult(str(index), f"week02-0{index}", index, ComponentStatus.PASS if index <= passes else ComponentStatus.FAIL, 0.25 if index <= passes else 0.0, 0.25, "PASS", "a" * 40, "TEST")
        for index in range(1, 5)
    )
    assert aggregate_component_results(values, 1.0)[1] == expected


def test_unverifiable_component_keeps_total_null() -> None:
    item = ComponentResult("one", "week02-01", 1, ComponentStatus.UNVERIFIABLE, None, 0.25, "CHECKER_ERROR", "a" * 40, "TEST")
    assert aggregate_component_results((item,), 0.25) == (ComponentStatus.UNVERIFIABLE, None)


def test_independent_oracles_cover_required_edges_and_pdf_erratum() -> None:
    assert expected_max([-2, -9, -1]) == -1
    assert expected_min([7, 2, -4]) == -4
    assert expected_negative_count([0, -1, 2, -3]) == 2
    assert expected_positive_sum_average([3, -1, 4, -2, 6, 0, 2]) == (15, 3.75)
    assert expected_positive_sum_average([0, -1, -2]) == (0, 0.0)
    assert expected_first_max_index([4, 9, 2, 9]) == 1
    assert expected_first_min_index([2, -3, 5, -3]) == 1
    avg_a, avg_b, errors, mae = expected_array_statistics([10, 20, 30, 40, 50], [12, 18, 33, 37, 55])
    assert (avg_a, avg_b, errors, mae) == (30.0, 31.0, (2, 2, 3, 3, 5), 3.0)
    assert expected_array_statistics([0, 0, 0], [1, 2, 3]) == (0.0, 2.0, (1, 2, 3), 2.0)
    assert expected_array_statistics([-5, 0, 5], [5, 0, -5]) == (0.0, 0.0, (10, 0, 10), 20 / 3)
    assert expected_array_statistics([1, 2], [1, 2])[-1] == 0.0


def test_array_oracle_detects_formula_bugs_on_independent_inputs() -> None:
    assert array_statistics_match("0 2 2", [0, 0, 0], [1, 2, 3])
    assert not array_statistics_match("0 2 -2", [0, 0, 0], [1, 2, 3])
    assert not array_statistics_match("0 0 6", [-5, 0, 5], [5, 0, -5])
    assert not array_statistics_match("30 31 3.4", [10, 20, 30, 40, 50], [12, 18, 33, 37, 55])


def test_practice7_does_not_require_intermediate_errors_in_stdout() -> None:
    assert validate_checker_output(CCheckerId.ARRAY_COMPARE_MAE, "Average A 30 Average B 31 MAE 3") == (
        True,
        "PASS",
    )


def test_practice7_output_order_and_labels_are_not_requirements() -> None:
    passed, reason = validate_checker_output(
        CCheckerId.ARRAY_COMPARE_MAE,
        "MAE 3.0 / 오차 5, 3, 3, 2, 2 / 평균 B 31 / 평균 A 30",
    )
    assert (passed, reason) == (True, "PASS")


def test_practice7_distinguishes_average_and_mae_failures() -> None:
    assert validate_checker_output(CCheckerId.ARRAY_COMPARE_MAE, "29 31 2 2 3 3 5 3") == (
        False,
        "AVERAGE_CALCULATION_INCORRECT",
    )
    assert validate_checker_output(CCheckerId.ARRAY_COMPARE_MAE, "30 31 2 2 3 3 5 MAE 3.4") == (
        False,
        "PDF_3_4_ERRATUM_RELATED",
    )


@pytest.mark.parametrize(
    ("checker", "correct_index", "last_index"),
    [
        (CCheckerId.MAX_INDEX_FIRST, "3", "5"),
        (CCheckerId.MIN_INDEX_FIRST, "2", "4"),
    ],
)
def test_first_match_checkers_distinguish_first_and_last_duplicate(
    checker: CCheckerId, correct_index: str, last_index: str
) -> None:
    assert validate_checker_output(checker, correct_index) == (True, "PASS")
    assert validate_checker_output(checker, last_index) == (
        False,
        "FIRST_MATCH_RULE_INCORRECT",
    )


@pytest.mark.parametrize(
    "source",
    [
        "double f(double*a,double*b){return fabs(a[0]-b[0]);}",
        "int f(int*a,int*b){return abs(a[0]-b[0]);}",
        "int main(void){int d=-2;if(d<0)d=-d;return d;}",
        "double f(double*a,double*b){return *a-*b;}",
        "double helper(double x){return x<0?-x:x;}",
    ],
)
def test_practice7_does_not_require_function_name_or_source_style(source: str) -> None:
    definition = GradingComponent("practice7", "week02-04", 7, 0.25, CCheckerId.ARRAY_COMPARE_MAE)
    project = RepositoryProjectSources("week02-04", True, (RepositorySourceFile("week02-04/custom.c", source),))
    result = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor("30 31 2 2 3 3 5 3"))
    assert result.status in {ComponentStatus.PASS, ComponentStatus.UNVERIFIABLE}
    assert result.status is not ComponentStatus.FAIL


def test_practice7_hardcoded_output_does_not_pass() -> None:
    definition = GradingComponent("practice7", "week02-04", 7, 0.25, CCheckerId.ARRAY_COMPARE_MAE)
    project = RepositoryProjectSources(
        "week02-04",
        True,
        (RepositorySourceFile("week02-04/main.c", 'int main(void){printf("30 31 3");return 0;}'),),
    )
    result = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor("30 31 3"))
    assert (result.status, result.reason) == (ComponentStatus.FAIL, "HARDCODED_OUTPUT")


def test_practice7_plausible_nonstandard_source_stays_unverifiable() -> None:
    assert classify_practice7_source((("custom.c", "int main(void){return custom_solution();}"),)) == "COMPUTATION_UNVERIFIABLE"


def test_practice7_computation_evidence_supports_behavioral_pass() -> None:
    source = """
    double absolute(double value) { return value < 0 ? -value : value; }
    int main(void) {
        double a[3] = {0, 1, 2}, b[3] = {1, 2, 3}, sum = 0;
        for (int i = 0; i < 3; ++i) sum += absolute(a[i] - b[i]);
        double mae = sum / 3;
        return mae < 0;
    }
    """
    assert classify_practice7_source((("main.c", source),)) == "COMPUTED"


def test_pdf_34_result_is_manual_review_not_automatic_failure() -> None:
    definition = GradingComponent("practice7", "week02-04", 7, 0.25, CCheckerId.ARRAY_COMPARE_MAE)
    source = "int main(void){double a[1],b[1],s=0;for(int i=0;i<1;i++)s+=fabs(a[i]-b[i]);s/=1;}"
    project = RepositoryProjectSources("week02-04", True, (RepositorySourceFile("week02-04/main.c", source),))
    result = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor("30 31 MAE 3.4"))
    assert (result.status, result.reason) == (ComponentStatus.UNVERIFIABLE, "PDF_3_4_ERRATUM_RELATED")


def test_compiler_specific_commands_are_isolated() -> None:
    source, executable = Path("source.c"), Path("program.exe")
    assert "/TC" in CCompiler(CCompilerKind.MSVC, "cl").compile_command((source,), executable)
    assert any(item.startswith("/Fe:") for item in CCompiler(CCompilerKind.MSVC, "cl").compile_command((source,), executable))
    for kind, name in ((CCompilerKind.CLANG, "clang"), (CCompilerKind.GCC, "gcc")):
        command = CCompiler(kind, name).compile_command((source,), executable)
        assert "-std=c11" in command and "-o" in command


def test_windows_discovery_prefers_msvc_without_mutating_environment(monkeypatch) -> None:
    import github_lab_grader.c_checker as checker
    before = dict(checker.os.environ)
    monkeypatch.setattr(checker.os, "name", "nt")
    monkeypatch.setattr(checker.shutil, "which", lambda name, **_kwargs: "cl.exe" if name == "cl" else None)
    assert discover_c_compiler().kind is CCompilerKind.MSVC
    assert dict(checker.os.environ) == before


def test_student_runtime_environment_excludes_credentials(tmp_path: Path, monkeypatch) -> None:
    import github_lab_grader.c_checker as checker
    monkeypatch.setenv("GITHUB_TOKEN", "fictional-secret")
    executor = checker.LocalCExecutor(CCompiler(CCompilerKind.CLANG, "clang"))
    environment = executor._runtime_environment(tmp_path)
    assert "GITHUB_TOKEN" not in environment
    assert "Authorization" not in environment


class OutputExecutor:
    def __init__(self, output: str | BaseException) -> None:
        self.output = output

    def run(self, _files):
        if isinstance(self.output, BaseException):
            raise self.output
        return ExecutionResult(self.output)


@pytest.mark.parametrize(
    ("checker", "output"),
    [
        (CCheckerId.MAX_VALUE, "최댓값: 9"),
        (CCheckerId.MIN_VALUE, "MIN = 1"),
        (CCheckerId.NEGATIVE_COUNT, "3"),
        (CCheckerId.POSITIVE_SUM_AVERAGE, "sum 15 count 4 average 3.75"),
        (CCheckerId.MAX_INDEX_FIRST, "index=3"),
        (CCheckerId.MIN_INDEX_FIRST, "2"),
        (CCheckerId.ARRAY_COMPARE_MAE, "30 31 | 2 2 3 3 5 | 3.0"),
    ],
)
def test_all_checker_ids_accept_numeric_semantics_without_exact_text(checker, output) -> None:
    definition = GradingComponent("practice", "week02-01", 1, 0.25, checker)
    source = (
        "double absolute(double x){return x<0?-x:x;} int main(void){double a[1],b[1],s=0;"
        "for(int i=0;i<1;i++)s+=absolute(a[i]-b[i]);s/=1;}"
        if checker is CCheckerId.ARRAY_COMPARE_MAE
        else "int solve(int *p, int n) { return p[0]; }"
    )
    project = RepositoryProjectSources("week02-01", True, (RepositorySourceFile("week02-01/solution.c", source),))
    result = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor(output))
    assert result.status is ComponentStatus.PASS


def test_checker_distinguishes_student_failure_from_execution_uncertainty() -> None:
    definition = GradingComponent("practice", "week02-01", 1, 0.25, CCheckerId.MAX_VALUE)
    project = RepositoryProjectSources("week02-01", True, (RepositorySourceFile("week02-01/custom.c", "int solve(int *p,int n){return 0;}"),))
    assert check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor("answer 8")).status is ComponentStatus.FAIL
    unresolved = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor(ExecutionUnavailable()))
    assert unresolved.status is ComponentStatus.UNVERIFIABLE and unresolved.score is None
    assert unresolved.reason == "GRADER_ENVIRONMENT_FAILURE"


def test_required_pointer_style_uncertainty_is_not_converted_to_failure() -> None:
    definition = GradingComponent("practice", "week02-01", 1, 0.25, CCheckerId.MAX_VALUE)
    project = RepositoryProjectSources("week02-01", True, (RepositorySourceFile("week02-01/alternative.c", "int main(void){return 0;}"),))
    result = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor("9"))
    assert result.status is ComponentStatus.UNVERIFIABLE
    assert result.reason == "POINTER_USAGE_UNVERIFIABLE"


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("2026-09-09T23:58:59+09:00", "ON_TIME"),
        ("2026-09-09T23:59:00+09:00", "ON_TIME"),
        ("2026-09-09T23:59:37+09:00", "ON_TIME"),
        ("2026-09-09T23:59:59+09:00", "ON_TIME"),
        ("2026-09-10T00:00:00+09:00", "NOT_SUBMITTED"),
        ("2026-09-09T14:59:59+00:00", "ON_TIME"),
    ],
)
def test_minute_resolution_deadline(when: str, expected: str) -> None:
    student = Student("01", "EXAMPLE001", "Example Student", "example-student", "example/repo")
    created = datetime.fromisoformat(when)
    from github_lab_grader.models import PushRecord
    push = PushRecord("1", student.github_id, created, "refs/heads/feature", "a" * 40, "b" * 40)
    coverage = EventCoverage(created + timedelta(days=1), 1, 1, created, created, False, True, True)
    decision = select_submission(
        RepositoryEventsResult((), (push,), (), coverage, ()), student, "main",
        resolve_section_deadline(RUBRIC, "01"), datetime(2026, 9, 11, tzinfo=UTC),
        settle_delay=timedelta(), history_max_age=timedelta(days=30), require_actor=True,
        use_late_window=False, enforce_submission_window_start=False, enforce_submission_branch=False,
    )
    assert decision.status.value == expected


def _course() -> CourseConfig:
    return CourseConfig(1, "2026-2", "Data Structures", "example-professor", "example-assistant", "Asia/Seoul", ("01", "02"), 14, 10.0, "2026-03-10", 0, 30, {})


@dataclass
class SnapshotGitHub:
    commits: tuple[CommitRecord, ...]
    projects_by_sha: dict[str, bool]

    def get_repository(self, repository):
        return RepositoryMetadata(1, repository, True, "private", "main", {"pull": True})

    def list_repository_events(self, _repository):
        fetched = datetime(2026, 9, 11, tzinfo=UTC)
        return RepositoryEventsResult((), (), (), EventCoverage(fetched, 1, 0, None, None, False, True, False), ())

    def list_repository_commits(self, _repository, _branch, _deadline):
        return CommitHistoryResult(self.commits, True)

    def get_c_sources_at_sha(self, _repository, sha, paths):
        exists = self.projects_by_sha[sha]
        return RepositorySourcesAtSha(sha, tuple(RepositoryProjectSources(path, exists, ()) for path in paths))


def _component_checker(definition, project, *, historical_sha, evidence_source):
    return ComponentResult(definition.component_id, definition.project_path, definition.practice_number, ComponentStatus.PASS if project.exists else ComponentStatus.FAIL, definition.max_score if project.exists else 0.0, definition.max_score, "PASS" if project.exists else "PROJECT_MISSING", historical_sha, evidence_source)


def test_commit_fallback_uses_latest_pre_deadline_snapshot_not_older_pass() -> None:
    earlier, later = "a" * 40, "b" * 40
    commits = (
        CommitRecord(earlier, None, datetime.fromisoformat("2026-09-09T20:00:00+09:00"), "main"),
        CommitRecord(later, None, datetime.fromisoformat("2026-09-09T22:00:00+09:00"), "main"),
    )
    github = SnapshotGitHub(commits, {earlier: True, later: False})
    student = Student("01", "EXAMPLE001", "Example Student", "example-student", "example/repo")
    result = GradingOrchestrator(github, _course(), now=lambda: datetime(2026, 9, 11, tzinfo=UTC), component_checker=_component_checker).grade_student(student, RUBRIC)
    assert result.selected_submission_sha == later
    assert result.score == 0.0


@pytest.mark.parametrize(("before_exists", "after_exists", "expected"), [(True, False, 1.0), (False, True, 0.0)])
def test_post_deadline_change_does_not_change_selected_snapshot(before_exists, after_exists, expected) -> None:
    before, after = "c" * 40, "d" * 40
    commits = (
        CommitRecord(before, None, datetime.fromisoformat("2026-09-09T23:00:00+09:00"), "main"),
        CommitRecord(after, None, datetime.fromisoformat("2026-09-10T09:00:00+09:00"), "main"),
    )
    github = SnapshotGitHub(commits, {before: before_exists, after: after_exists})
    student = Student("01", "EXAMPLE001", "Example Student", "example-student", "example/repo")
    result = GradingOrchestrator(github, _course(), now=lambda: datetime(2026, 9, 11, tzinfo=UTC), component_checker=_component_checker).grade_student(student, RUBRIC)
    assert result.selected_submission_sha == before
    assert result.score == expected


def test_checker_internal_failure_is_unverifiable() -> None:
    definition = GradingComponent("practice", "week02-01", 1, 0.25, CCheckerId.MAX_VALUE)
    project = RepositoryProjectSources("week02-01", True, (RepositorySourceFile("week02-01/custom.c", "int solve(int *p,int n){return p[0];}"),))
    result = check_c_submission(definition, project, historical_sha="a" * 40, evidence_source="TEST", executor=OutputExecutor(RuntimeError("fictional checker fault")))
    assert result.status is ComponentStatus.UNVERIFIABLE
    assert result.reason == "CHECKER_ERROR" and result.score is None


def test_missing_project_and_source_are_reliable_component_failures() -> None:
    definition = GradingComponent("practice", "week02-01", 1, 0.25, CCheckerId.MAX_VALUE)
    missing = check_c_submission(definition, RepositoryProjectSources("week02-01", False, ()), historical_sha="a" * 40, evidence_source="TEST")
    empty = check_c_submission(definition, RepositoryProjectSources("week02-01", True, ()), historical_sha="a" * 40, evidence_source="TEST")
    assert (missing.status, missing.score, missing.reason) == (ComponentStatus.FAIL, 0.0, "PROJECT_MISSING")
    assert (empty.status, empty.score, empty.reason) == (ComponentStatus.FAIL, 0.0, "NO_RELEVANT_SOURCE")


def test_historical_source_retrieval_failure_keeps_week_total_null() -> None:
    before = "e" * 40

    class BrokenSources(SnapshotGitHub):
        def get_c_sources_at_sha(self, _repository, _sha, _paths):
            raise GitHubApiError(GitHubErrorCode.API_ERROR, "fictional source failure")

    commits = (CommitRecord(before, None, datetime.fromisoformat("2026-09-09T23:00:00+09:00"), "main"),)
    github = BrokenSources(commits, {before: True})
    student = Student("01", "EXAMPLE001", "Example Student", "example-student", "example/repo")
    result = GradingOrchestrator(github, _course(), now=lambda: datetime(2026, 9, 11, tzinfo=UTC), component_checker=_component_checker).grade_student(student, RUBRIC)
    assert result.score is None
    assert all(item.status is ComponentStatus.UNVERIFIABLE for item in result.component_results)
