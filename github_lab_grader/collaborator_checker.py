"""현재 collaborator 증거가 README 평가로 진행 가능한지 판정한다."""

from __future__ import annotations

from .models import CollaboratorStatus


def collaborators_allow_readme_check(
    professor: CollaboratorStatus,
    assistant: CollaboratorStatus,
) -> bool:
    """두 필수 collaborator가 모두 ACTIVE일 때만 추가 API 조회를 허용한다."""

    return professor is CollaboratorStatus.ACTIVE and assistant is CollaboratorStatus.ACTIVE
