"""Week 2 C 실습을 격리 실행 결과와 독립 oracle로 보수적으로 판정한다."""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from pathlib import PurePosixPath

from .models import CCheckerId, ComponentResult, ComponentStatus, GradingComponent, RepositoryProjectSources

_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_MAE_VALUE = re.compile(
    r"(?:\bMAE\b|평균\s*절대\s*오차)\s*[:=]?\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)
_POINTER_PARAMETER = re.compile(
    r"\([^)]*\b(?:char|short|int|long|float|double)\s*(?:\*\s*\w+|\w+\s*\[\s*\])",
    re.MULTILINE,
)
_C_COMMENT = re.compile(r"/\*.*?\*/|//[^\r\n]*", re.DOTALL)
_C_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_PRACTICE7_UNVERIFIABLE = {
    "COMPUTATION_UNVERIFIABLE",
    "PDF_3_4_ERRATUM_RELATED",
}


def expected_max(values: Sequence[int]) -> int:
    return max(values)


def expected_min(values: Sequence[int]) -> int:
    return min(values)


def expected_negative_count(values: Sequence[int]) -> int:
    return sum(value < 0 for value in values)


def expected_positive_sum_average(values: Sequence[int]) -> tuple[int, float]:
    positive = [value for value in values if value > 0]
    return sum(positive), sum(positive) / len(positive) if positive else 0.0


def expected_first_max_index(values: Sequence[int]) -> int:
    return values.index(max(values))


def expected_first_min_index(values: Sequence[int]) -> int:
    return values.index(min(values))


def expected_array_statistics(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, tuple[float, ...], float]:
    if not first or len(first) != len(second):
        raise ValueError("equal non-empty arrays are required")
    errors = tuple(abs(left - right) for left, right in zip(first, second))
    return sum(first) / len(first), sum(second) / len(second), errors, sum(errors) / len(errors)


_EXPECTED = {
    CCheckerId.MAX_VALUE: (9.0,),
    CCheckerId.MIN_VALUE: (1.0,),
    CCheckerId.NEGATIVE_COUNT: (3.0,),
    CCheckerId.POSITIVE_SUM_AVERAGE: (15.0, 3.75),
    CCheckerId.MAX_INDEX_FIRST: (3.0,),
    CCheckerId.MIN_INDEX_FIRST: (2.0,),
    # PDF의 3.4 오기는 사용하지 않고 명시된 MAE 공식으로 계산한다.
    CCheckerId.ARRAY_COMPARE_MAE: (30.0, 31.0, 2.0, 2.0, 3.0, 3.0, 5.0, 3.0),
}

_FAIL_REASON = {
    CCheckerId.MAX_VALUE: "MAX_VALUE_INCORRECT",
    CCheckerId.MIN_VALUE: "MIN_VALUE_INCORRECT",
    CCheckerId.NEGATIVE_COUNT: "NEGATIVE_COUNT_INCORRECT",
    CCheckerId.POSITIVE_SUM_AVERAGE: "POSITIVE_SUM_AVERAGE_INCORRECT",
    CCheckerId.MAX_INDEX_FIRST: "FIRST_MATCH_RULE_INCORRECT",
    CCheckerId.MIN_INDEX_FIRST: "FIRST_MATCH_RULE_INCORRECT",
    CCheckerId.ARRAY_COMPARE_MAE: "MAE_CALCULATION_INCORRECT",
}


class ExecutionUnavailable(RuntimeError):
    def __init__(self, reason_code: str = "GRADER_ENVIRONMENT_FAILURE") -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class StudentProgramError(RuntimeError):
    pass


class CCompilerKind(StrEnum):
    MSVC = "MSVC"
    GCC = "GCC"
    CLANG = "CLANG"


@dataclass(frozen=True, slots=True)
class CCompiler:
    kind: CCompilerKind
    executable: str
    environment: dict[str, str] | None = None

    def compile_command(self, sources: Sequence[Path], executable: Path) -> list[str]:
        if self.kind is CCompilerKind.MSVC:
            return [
                self.executable,
                "/nologo",
                "/TC",
                *map(str, sources),
                f"/Fe:{executable}",
            ]
        command = [self.executable, "-std=c11", *map(str, sources), "-o", str(executable)]
        if os.name != "nt":
            command.append("-lm")
        return command


@dataclass(frozen=True, slots=True)
class CompilerProbe:
    available: bool
    compiler: CCompiler | None
    identity: str | None = None


def _start_process_with_policy_retry(command: Sequence[str], **kwargs) -> subprocess.Popen:
    """컴파일 직후 Windows 보안 검사가 실행을 잠시 보류하는 경우만 제한 재시도한다."""

    for attempt in range(5):
        try:
            return subprocess.Popen(command, **kwargs)
        except OSError as exc:
            if getattr(exc, "winerror", None) != 4551 or attempt == 4:
                raise
            time.sleep(0.25)
    raise AssertionError("bounded process retry exhausted")


def _run_with_policy_retry(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    for attempt in range(5):
        try:
            return subprocess.run(command, **kwargs)
        except OSError as exc:
            if getattr(exc, "winerror", None) != 4551 or attempt == 4:
                raise
            time.sleep(0.25)
    raise AssertionError("bounded process retry exhausted")


def _compiler_from_path(path: str, environment: dict[str, str] | None = None) -> CCompiler | None:
    name = Path(path).name.casefold()
    if name in {"cl", "cl.exe"}:
        kind = CCompilerKind.MSVC
    elif name in {"gcc", "gcc.exe"}:
        kind = CCompilerKind.GCC
    elif name in {"clang", "clang.exe"}:
        kind = CCompilerKind.CLANG
    else:
        return None
    prepared = dict(environment or os.environ)
    prepared["PATH"] = os.pathsep.join((str(Path(path).parent), prepared.get("PATH", "")))
    return CCompiler(kind, path, prepared)


def _visual_studio_compiler() -> CCompiler | None:
    """설치 metadata로 MSVC를 찾되 parent process 환경은 변경하지 않는다."""

    if os.name != "nt":
        return None
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        found = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            text=True,
        )
        root = Path(found.stdout.strip())
        developer_script = root / "Common7/Tools/VsDevCmd.bat"
        if found.returncode or not developer_script.is_file():
            return None
        # cmd.exe의 중첩 인용 규칙에 의존하지 않도록 일회용 wrapper에서만
        # VsDevCmd를 호출한다. 얻은 환경은 compiler subprocess에만 전달한다.
        with tempfile.TemporaryDirectory(prefix="ds-ta-msvc-env-") as directory:
            wrapper = Path(directory) / "environment.cmd"
            wrapper.write_text(
                f'@call "{developer_script}" -arch=x64 -host_arch=x64 >nul\n@set\n',
                encoding="utf-8",
            )
            environment_result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(wrapper)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
                text=True,
                errors="replace",
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if environment_result.returncode:
        return None
    environment = dict(os.environ)
    for line in environment_result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            environment[key] = value
    executable = shutil.which("cl", path=environment.get("PATH"))
    return CCompiler(CCompilerKind.MSVC, executable, environment) if executable else None


def discover_c_compilers(explicit: str | None = None) -> tuple[CCompiler, ...]:
    """명시 설정, MSVC, Clang, GCC 순서의 중복 없는 후보를 반환한다."""

    if explicit:
        resolved = shutil.which(explicit) or (explicit if Path(explicit).is_file() else None)
        compiler = _compiler_from_path(resolved) if resolved else None
        return (compiler,) if compiler else ()
    candidates: list[CCompiler] = []
    if os.name == "nt":
        cl = shutil.which("cl")
        if cl:
            candidates.append(CCompiler(CCompilerKind.MSVC, cl, dict(os.environ)))
        else:
            installed_msvc = _visual_studio_compiler()
            if installed_msvc:
                candidates.append(installed_msvc)
    for name in ("clang", "gcc"):
        executable = shutil.which(name)
        if executable:
            compiler = _compiler_from_path(executable, dict(os.environ))
            if compiler:
                candidates.append(compiler)
    return tuple(candidates)


def discover_c_compiler(explicit: str | None = None) -> CCompiler | None:
    candidates = discover_c_compilers(explicit)
    return candidates[0] if candidates else None


def probe_c_compiler(compiler: CCompiler | None, *, timeout_seconds: float = 5.0) -> CompilerProbe:
    """학생 코드와 무관한 최소 프로그램의 compile/run으로 toolchain 전체를 확인한다."""

    if compiler is None:
        return CompilerProbe(False, None)
    try:
        with tempfile.TemporaryDirectory(prefix="ds-ta-c-probe-") as directory:
            root = Path(directory)
            source = root / "probe.c"
            executable = root / ("probe.exe" if os.name == "nt" else "probe")
            source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            compiled = subprocess.run(
                compiler.compile_command((source,), executable),
                cwd=root,
                env=compiler.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
            if compiled.returncode or not executable.is_file():
                return CompilerProbe(False, compiler)
            ran = _run_with_policy_retry(
                [str(executable)], cwd=root, env=compiler.environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout_seconds, check=False,
            )
            if ran.returncode:
                return CompilerProbe(False, compiler)
            version_command = [compiler.executable] if compiler.kind is CCompilerKind.MSVC else [compiler.executable, "--version"]
            version = subprocess.run(
                version_command, env=compiler.environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout_seconds,
                check=False, text=True, encoding="utf-8", errors="replace",
            ).stdout.splitlines()
            identity = version[0].strip() if version else compiler.kind.value
            return CompilerProbe(True, compiler, identity)
    except (OSError, subprocess.TimeoutExpired):
        return CompilerProbe(False, compiler)


def probe_available_c_compiler(explicit: str | None = None) -> CompilerProbe:
    """우선 후보가 깨졌을 때도 다음 compiler를 검사해 usable toolchain을 찾는다."""

    last: CCompiler | None = None
    for compiler in discover_c_compilers(explicit):
        last = compiler
        result = probe_c_compiler(compiler)
        if result.available:
            return result
    return CompilerProbe(False, last)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    output: str


class LocalCExecutor:
    """발견된 compiler로 임시 복사본만 실행하며 시간과 출력을 제한한다."""

    def __init__(self, compiler: str | CCompiler | None = None, *, timeout_seconds: float = 3.0) -> None:
        self.compilers = (
            (compiler,)
            if isinstance(compiler, CCompiler)
            else discover_c_compilers(compiler)
        )
        self.compiler = self.compilers[0] if self.compilers else None
        self.timeout_seconds = timeout_seconds

    def _runtime_environment(self, root: Path, compiler: CCompiler | None = None) -> dict[str, str]:
        """학생 process에는 credential 등 parent 환경을 전달하지 않는다."""

        environment = {"TEMP": str(root), "TMP": str(root)}
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            environment.update(
                {
                    "SystemRoot": system_root,
                    "WINDIR": system_root,
                    "PATH": os.pathsep.join(
                        (str(Path((compiler or self.compiler).executable).parent), str(Path(system_root) / "System32"))
                    ),
                    "PATHEXT": ".COM;.EXE;.BAT;.CMD",
                }
            )
        else:
            environment["PATH"] = "/usr/bin:/bin"
        return environment

    def run(self, files: Sequence[tuple[str, str]]) -> ExecutionResult:
        if not self.compiler:
            raise ExecutionUnavailable("GRADER_ENVIRONMENT_FAILURE")
        with tempfile.TemporaryDirectory(prefix="ds-ta-c-") as directory:
            root = Path(directory)
            paths: list[Path] = []
            for name, content in files:
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ExecutionUnavailable("GRADER_ENVIRONMENT_FAILURE")
                path = root.joinpath(*relative.parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                if path.suffix.casefold() == ".c":
                    paths.append(path)
            compiled_once = False
            for compiler in self.compilers:
                executable = root / (f"student-{compiler.kind.value.casefold()}.exe" if os.name == "nt" else f"student-{compiler.kind.value.casefold()}")
                try:
                    compiled = subprocess.run(
                        compiler.compile_command(paths, executable), cwd=root,
                        env=compiler.environment,
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=self.timeout_seconds, check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if compiled.returncode or not executable.is_file():
                    # 한 compiler의 dialect 차이만으로 학생 실패를 확정하지 않는다.
                    continue
                compiled_once = True
                output_path = root / f"program-output-{compiler.kind.value.casefold()}.txt"
                try:
                    with output_path.open("wb") as output:
                        process = _start_process_with_policy_retry(
                            [str(executable)], cwd=root, stdin=subprocess.DEVNULL,
                            stdout=output, stderr=subprocess.STDOUT,
                            env=self._runtime_environment(root, compiler),
                        )
                        deadline = time.monotonic() + self.timeout_seconds
                        while process.poll() is None:
                            if time.monotonic() >= deadline or output.tell() > 64 * 1024:
                                process.kill()
                                process.wait()
                                raise StudentProgramError("student program exceeded execution limits")
                            time.sleep(0.01)
                except OSError:
                    continue
                raw = output_path.read_bytes()
                if len(raw) > 64 * 1024 or process.returncode:
                    raise StudentProgramError("student program did not complete within limits")
                return ExecutionResult(raw.decode("utf-8", errors="replace"))
            if compiled_once:
                raise ExecutionUnavailable("GRADER_ENVIRONMENT_FAILURE")
            raise ExecutionUnavailable(
                "UNSUPPORTED_PLAUSIBLE_IMPLEMENTATION"
                if len(paths) > 1
                else "STUDENT_SOURCE_COMPILE_FAILURE"
            )


def _contains_expected_numbers(output: str, expected: Sequence[float]) -> bool:
    numbers = [float(item.group()) for item in _NUMBER.finditer(output)]
    position = 0
    for target in expected:
        while position < len(numbers) and not math.isclose(numbers[position], target, rel_tol=1e-7, abs_tol=1e-7):
            position += 1
        if position == len(numbers):
            return False
        position += 1
    return True


def _contains_expected_multiset(output: str, expected: Sequence[float]) -> bool:
    """문구와 출력 순서는 rubric 조건이 아니므로 필요한 수치의 개수만 확인한다."""

    remaining = [float(item.group()) for item in _NUMBER.finditer(output)]
    for target in expected:
        match = next(
            (index for index, value in enumerate(remaining) if math.isclose(value, target, rel_tol=1e-6, abs_tol=1e-6)),
            None,
        )
        if match is None:
            return False
        remaining.pop(match)
    return True


def array_statistics_match(
    output: str, first: Sequence[float], second: Sequence[float]
) -> bool:
    average_a, average_b, _errors, mae = expected_array_statistics(first, second)
    labeled_mae = _MAE_VALUE.search(output)
    if labeled_mae and not math.isclose(float(labeled_mae.group(1)), mae, rel_tol=1e-6, abs_tol=1e-6):
        return False
    # 중간 절대오차를 stdout에 모두 인쇄하는 것은 rubric 조건이 아니다.
    return _contains_expected_multiset(output, (average_a, average_b, mae))


def validate_checker_output(checker: CCheckerId, output: str) -> tuple[bool, str]:
    if checker is CCheckerId.ARRAY_COMPARE_MAE:
        first = (10.0, 20.0, 30.0, 40.0, 50.0)
        second = (12.0, 18.0, 33.0, 37.0, 55.0)
        if array_statistics_match(output, first, second):
            return True, "PASS"
        average_a, average_b, _, _ = expected_array_statistics(first, second)
        if not _contains_expected_multiset(output, (average_a, average_b)):
            return False, "AVERAGE_CALCULATION_INCORRECT"
        labeled_mae = _MAE_VALUE.search(output)
        if labeled_mae and math.isclose(float(labeled_mae.group(1)), 3.4, rel_tol=1e-7, abs_tol=1e-7):
            return False, "PDF_3_4_ERRATUM_RELATED"
        return False, "MAE_CALCULATION_INCORRECT"
    return (
        (True, "PASS")
        if _contains_expected_numbers(output, _EXPECTED[checker])
        else (False, _FAIL_REASON[checker])
    )


def classify_practice7_source(files: Sequence[tuple[str, str]]) -> str:
    """명확한 계산 증거만 승인하며 비표준 구조는 실패 대신 불확실로 남긴다."""

    source = "\n".join(content for _name, content in files)
    uncommented = _C_COMMENT.sub(" ", source)
    strings = " ".join(_C_STRING.findall(uncommented))
    code = _C_STRING.sub(" ", uncommented)
    has_iteration = bool(re.search(r"\b(?:for|while)\s*\(", code))
    has_array_access = bool(re.search(r"\[[^\]]*\]", code))
    has_division = "/" in code
    has_absolute = bool(
        re.search(r"\b(?:fabs|fabsf|abs|labs)\s*\(", code)
        or re.search(r"\bif\s*\([^)]*(?:<\s*0|>\s*0)", code)
        or re.search(r"\?[^:]*-", code)
    )
    if has_iteration and has_array_access and has_division and has_absolute:
        return "COMPUTED"
    if all(re.search(pattern, strings) for pattern in (r"(?<!\d)30(?:\.0+)?(?!\d)", r"(?<!\d)31(?:\.0+)?(?!\d)", r"(?<!\d)3(?:\.0+)?(?!\d)")) and not any(
        (has_iteration, has_division, has_absolute)
    ):
        return "HARDCODED_OUTPUT"
    return "COMPUTATION_UNVERIFIABLE"


def aggregate_component_results(
    results: Sequence[ComponentResult], max_score: float
) -> tuple[ComponentStatus, float | None]:
    """한 component라도 불확실하면 총점을 확정하지 않는다."""

    if any(item.status is ComponentStatus.UNVERIFIABLE for item in results):
        return ComponentStatus.UNVERIFIABLE, None
    score = sum(item.score or 0.0 for item in results)
    return (ComponentStatus.PASS if math.isclose(score, max_score) else ComponentStatus.FAIL), score


def check_c_submission(
    component: GradingComponent,
    project: RepositoryProjectSources,
    *,
    historical_sha: str,
    evidence_source: str,
    executor: LocalCExecutor | None = None,
) -> ComponentResult:
    """명확한 실행 결과만 PASS/FAIL로 확정하고 도구 불확실성은 null로 남긴다."""

    common = (component.component_id, component.project_path, component.practice_number)
    if not project.exists:
        return ComponentResult(*common, ComponentStatus.FAIL, 0.0, component.max_score, "PROJECT_MISSING", historical_sha, evidence_source)
    if not any(source.path.casefold().endswith(".c") for source in project.files):
        return ComponentResult(*common, ComponentStatus.FAIL, 0.0, component.max_score, "NO_RELEVANT_SOURCE", historical_sha, evidence_source)
    try:
        result = (executor or LocalCExecutor()).run(tuple((source.path, source.content) for source in project.files))
    except ExecutionUnavailable as exc:
        return ComponentResult(*common, ComponentStatus.UNVERIFIABLE, None, component.max_score, exc.reason_code, historical_sha, evidence_source)
    except StudentProgramError:
        return ComponentResult(*common, ComponentStatus.FAIL, 0.0, component.max_score, "CORE_BEHAVIOR_INCORRECT", historical_sha, evidence_source)
    except Exception:
        return ComponentResult(*common, ComponentStatus.UNVERIFIABLE, None, component.max_score, "CHECKER_ERROR", historical_sha, evidence_source)
    passed, reason = validate_checker_output(component.checker, result.output)
    if passed:
        if component.checker is CCheckerId.ARRAY_COMPARE_MAE:
            source_classification = classify_practice7_source(
                tuple((source.path, source.content) for source in project.files)
            )
            if source_classification == "HARDCODED_OUTPUT":
                return ComponentResult(*common, ComponentStatus.FAIL, 0.0, component.max_score, source_classification, historical_sha, evidence_source)
            if source_classification != "COMPUTED":
                return ComponentResult(*common, ComponentStatus.UNVERIFIABLE, None, component.max_score, source_classification, historical_sha, evidence_source)
        if component.checker in {CCheckerId.MAX_VALUE, CCheckerId.NEGATIVE_COUNT} and not any(
            _POINTER_PARAMETER.search(source.content) for source in project.files
        ):
            return ComponentResult(*common, ComponentStatus.UNVERIFIABLE, None, component.max_score, "POINTER_USAGE_UNVERIFIABLE", historical_sha, evidence_source)
        return ComponentResult(*common, ComponentStatus.PASS, component.max_score, component.max_score, "PASS", historical_sha, evidence_source)
    if reason in _PRACTICE7_UNVERIFIABLE:
        return ComponentResult(*common, ComponentStatus.UNVERIFIABLE, None, component.max_score, reason, historical_sha, evidence_source)
    return ComponentResult(*common, ComponentStatus.FAIL, 0.0, component.max_score, reason, historical_sha, evidence_source)
