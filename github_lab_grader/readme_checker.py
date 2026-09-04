"""선택된 SHA의 README text에서 학생 identity를 검사하는 순수 계층."""

from __future__ import annotations

import re
import unicodedata

from .models import ReadmeIdentityResult, ReadmeStatus, Student


def _contains_exact(normalized_text: str, expected: str) -> bool:
    normalized_expected = unicodedata.normalize("NFC", expected)
    if not normalized_expected:
        return False
    pattern = rf"(?<!\w){re.escape(normalized_expected)}(?!\w)"
    return re.search(pattern, normalized_text) is not None


def check_readme_identity(text: str, student: Student) -> ReadmeIdentityResult:
    """NFC 정규화 뒤 ID와 이름을 fuzzy matching 없이 독립적으로 확인한다."""

    normalized = unicodedata.normalize("NFC", text)
    student_id_found = _contains_exact(normalized, student.student_id)
    student_name_found = _contains_exact(normalized, student.name)
    status = (
        ReadmeStatus.COMPLETE
        if student_id_found and student_name_found
        else ReadmeStatus.INCOMPLETE
    )
    return ReadmeIdentityResult(status, student_id_found, student_name_found)
