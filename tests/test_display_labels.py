from enum import StrEnum

from github_lab_grader import models
from github_lab_grader.auth import AuthSource
from github_lab_grader.c_checker import CCompilerKind
from github_lab_grader.display_labels import LABELS, format_component_status, format_display_label
from github_lab_grader.gradebook import CompletionStatus, WeekReportStatus
from github_lab_grader.preflight import PreflightSeverity


def test_representative_korean_labels_preserve_internal_codes() -> None:
    assert format_display_label("PROJECT_MISSING") == "프로젝트 폴더를 찾을 수 없음 (PROJECT_MISSING)"
    assert format_component_status("FAIL") == "미충족 (FAIL)"
    assert format_display_label("MISSING_REPOSITORY_INFO").endswith("(MISSING_REPOSITORY_INFO)")


def test_unknown_code_has_safe_non_crashing_fallback() -> None:
    assert format_display_label("UNKNOWN_NEW_CODE") == "알 수 없는 판정 사유 (UNKNOWN_NEW_CODE)"


def test_all_operator_visible_enum_values_have_labels() -> None:
    enum_types = [
        value for value in vars(models).values()
        if isinstance(value, type) and issubclass(value, StrEnum)
    ] + [WeekReportStatus, CompletionStatus, PreflightSeverity, AuthSource, CCompilerKind]
    missing = {item.value for enum_type in enum_types for item in enum_type if item.value not in LABELS}
    assert missing == set()
