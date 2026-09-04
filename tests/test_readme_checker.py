"""root README 선택과 NFC identity matching 테스트."""

import unicodedata

from github_lab_grader.github_client import GitHubClient
from github_lab_grader.models import ReadmeStatus, Student
from github_lab_grader.readme_checker import check_readme_identity


STUDENT = Student("01", "EXAMPLE001", "가상학생", "student-example", "owner/repo")


def test_korean_name_matches_after_nfc_normalization() -> None:
    decomposed = unicodedata.normalize("NFD", STUDENT.name)
    result = check_readme_identity(f"학번: EXAMPLE001\n이름: {decomposed}", STUDENT)
    assert result.status is ReadmeStatus.COMPLETE


def test_root_readme_case_variants_are_accepted() -> None:
    entries = ({"type": "file", "name": "README.MD", "path": "README.MD"},)
    assert GitHubClient.find_root_readme(entries) == "README.MD"


def test_nested_readme_is_not_accepted() -> None:
    entries = ({"type": "file", "name": "README.md", "path": "docs/README.md"},)
    assert GitHubClient.find_root_readme(entries) is None


def test_each_missing_identity_field_is_incomplete() -> None:
    assert check_readme_identity("EXAMPLE001", STUDENT).status is ReadmeStatus.INCOMPLETE
    assert check_readme_identity("가상학생", STUDENT).status is ReadmeStatus.INCOMPLETE


def test_missing_both_identity_fields_is_incomplete() -> None:
    result = check_readme_identity("공개 가능한 예시 README", STUDENT)
    assert result.status is ReadmeStatus.INCOMPLETE
    assert not result.student_id_found
    assert not result.student_name_found


def test_identity_substrings_are_not_exact_matches() -> None:
    result = check_readme_identity("EXAMPLE0019 가상학생추가", STUDENT)
    assert result.status is ReadmeStatus.INCOMPLETE
    assert not result.student_id_found
    assert not result.student_name_found
