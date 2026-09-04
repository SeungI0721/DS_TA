"""GitHub 인증정보를 노출하지 않고 순서대로 탐색하는 provider를 제공한다."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values


class AuthSource(StrEnum):
    GITHUB_CLI = "GITHUB_CLI"
    ENVIRONMENT = "ENVIRONMENT"
    DOTENV = "DOTENV"


@dataclass(frozen=True, slots=True)
class AuthCredential:
    """실제 token이 repr 또는 예외 문자열에 포함되지 않도록 보관한다."""

    token: str = field(repr=False)
    source: AuthSource

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError("token must not be empty")


class AuthProvider(Protocol):
    def get_credential(self) -> AuthCredential | None:
        """사용 가능한 credential을 반환하며, 없으면 None을 반환한다."""


@dataclass(slots=True)
class GitHubCLIAuthProvider:
    command_timeout_seconds: float = 10.0

    def get_credential(self) -> AuthCredential | None:
        gh = shutil.which("gh")
        if gh is None:
            return None
        try:
            result = subprocess.run(
                [gh, "auth", "token"],
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        token = result.stdout.strip() if result.returncode == 0 else ""
        return AuthCredential(token, AuthSource.GITHUB_CLI) if token else None


@dataclass(slots=True)
class EnvironmentAuthProvider:
    variable_name: str = "GITHUB_TOKEN"

    def get_credential(self) -> AuthCredential | None:
        token = os.environ.get(self.variable_name, "").strip()
        return AuthCredential(token, AuthSource.ENVIRONMENT) if token else None


@dataclass(slots=True)
class DotEnvAuthProvider:
    path: Path = Path(".env")
    variable_name: str = "GITHUB_TOKEN"

    def get_credential(self) -> AuthCredential | None:
        if not self.path.is_file():
            return None
        token = (dotenv_values(self.path).get(self.variable_name) or "").strip()
        return AuthCredential(token, AuthSource.DOTENV) if token else None


@dataclass(slots=True)
class CompositeAuthProvider:
    providers: tuple[AuthProvider, ...]

    def get_credential(self) -> AuthCredential | None:
        for provider in self.providers:
            credential = provider.get_credential()
            if credential is not None:
                return credential
        return None


def default_auth_provider(dotenv_path: Path = Path(".env")) -> CompositeAuthProvider:
    """GitHub CLI, process environment, .env 순서의 기본 provider를 만든다."""

    return CompositeAuthProvider(
        (
            GitHubCLIAuthProvider(),
            EnvironmentAuthProvider(),
            DotEnvAuthProvider(dotenv_path),
        )
    )
