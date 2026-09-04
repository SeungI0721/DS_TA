"""향후 persistence와 workbook의 acceptance 명세."""

import pytest


@pytest.mark.skip(reason="Immutable persistence is scheduled for Phase 5")
def test_existing_record_refuses_overwrite_without_regrade():
    pass


@pytest.mark.skip(reason="Gradebook generation is scheduled for Phase 6")
def test_ungraded_week_is_blank_not_zero():
    pass
