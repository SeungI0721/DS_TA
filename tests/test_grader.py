"""Executable specifications for Phase 3 pure score calculation."""

import pytest


PHASE_3 = pytest.mark.skip(reason="Behavioral implementation is scheduled for Phase 3")


@PHASE_3
def test_valid_submission_collaborators_and_identity_receive_full_score():
    pass


@PHASE_3
def test_missing_one_identity_field_receives_partial_score():
    pass


@PHASE_3
def test_missing_both_identity_fields_still_receives_partial_score():
    pass


@PHASE_3
def test_missing_readme_receives_zero():
    pass


@PHASE_3
def test_missing_professor_collaborator_receives_zero():
    pass


@PHASE_3
def test_missing_assistant_collaborator_receives_zero():
    pass


@PHASE_3
def test_collaborator_uncertainty_requires_manual_review():
    pass


@PHASE_3
def test_unverifiable_events_do_not_become_zero():
    pass
