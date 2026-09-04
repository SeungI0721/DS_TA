"""Executable specifications for Phase 3 README identity logic."""

import pytest


PHASE_3 = pytest.mark.skip(reason="Behavioral implementation is scheduled for Phase 3")


@PHASE_3
def test_korean_name_matches_after_nfc_normalization():
    pass


@PHASE_3
def test_root_readme_case_variants_are_accepted():
    pass


@PHASE_3
def test_nested_readme_is_not_accepted():
    pass


@PHASE_3
def test_readme_changed_after_deadline_is_evaluated_at_selected_sha_only():
    pass


@PHASE_3
def test_readme_created_only_after_deadline_does_not_count():
    pass
