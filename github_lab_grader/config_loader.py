"""설정 파일 loading과 validation을 분리하기 위한 경계."""

from __future__ import annotations

from pathlib import Path

from .models import Student, WeeklyRubric


class ConfigurationError(ValueError):
    """설정이 없거나 형식 및 내부 관계가 올바르지 않을 때 발생한다."""


def load_global_config(path: Path) -> dict[str, object]:
    raise NotImplementedError("Full configuration loading is not implemented")


def load_students(path: Path) -> list[Student]:
    raise NotImplementedError("Student CSV loading is not implemented")


def load_weekly_rubric(path: Path) -> WeeklyRubric:
    raise NotImplementedError("Rubric loading is not implemented")
