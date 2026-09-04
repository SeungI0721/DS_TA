"""Configuration-loading boundary; parsing and validation arrive in Phase 3."""

from __future__ import annotations

from pathlib import Path

from .models import Student, WeeklyRubric


class ConfigurationError(ValueError):
    """Configuration is missing, malformed, or internally inconsistent."""


def load_global_config(path: Path) -> dict[str, object]:
    raise NotImplementedError("Configuration parsing is scheduled for Phase 3")


def load_students(path: Path) -> list[Student]:
    raise NotImplementedError("Student CSV parsing is scheduled for Phase 3")


def load_weekly_rubric(path: Path) -> WeeklyRubric:
    raise NotImplementedError("Rubric parsing is scheduled for Phase 3")

