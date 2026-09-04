from __future__ import annotations

from datetime import UTC, datetime

import pytest

from github_lab_grader.models import PushRecord, Student


@pytest.fixture
def fake_student() -> Student:
    return Student("01", "EXAMPLE001", "Example Student", "student-example", "student-example/lab")


@pytest.fixture
def push_factory():
    def make(when: datetime, *, event_id: str = "event-1", head: str = "a" * 40) -> PushRecord:
        assert when.tzinfo is not None
        return PushRecord(
            event_id,
            "student-example",
            when.astimezone(UTC),
            "refs/heads/main",
            head,
            "b" * 40,
            1,
        )

    return make

