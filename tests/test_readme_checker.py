"""향후 README identity 순수 로직의 실행 가능한 명세."""

import pytest


PHASE_4 = pytest.mark.skip(reason="README identity grading is scheduled for Phase 4")


@PHASE_4
def test_korean_name_matches_after_nfc_normalization():
    pass


@PHASE_4
def test_root_readme_case_variants_are_accepted():
    pass


@PHASE_4
def test_nested_readme_is_not_accepted():
    pass


@PHASE_4
def test_readme_changed_after_deadline_is_evaluated_at_selected_sha_only():
    pass


@PHASE_4
def test_readme_created_only_after_deadline_does_not_count():
    pass
