from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from github_lab_grader.auth import (
    AuthCredential,
    AuthSource,
    CompositeAuthProvider,
    DotEnvAuthProvider,
    EnvironmentAuthProvider,
    GitHubCLIAuthProvider,
)


def test_cli_auth_returns_token_without_exposing_it_in_repr(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "gh")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="secret-token\n"),
    )
    credential = GitHubCLIAuthProvider().get_credential()
    assert credential is not None
    assert credential.source is AuthSource.GITHUB_CLI
    assert "secret-token" not in repr(credential)


def test_environment_auth(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "environment-token")
    credential = EnvironmentAuthProvider().get_credential()
    assert credential is not None
    assert credential.source is AuthSource.ENVIRONMENT


def test_dotenv_auth(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("GITHUB_TOKEN=dotenv-token\n", encoding="utf-8")
    credential = DotEnvAuthProvider(path).get_credential()
    assert credential is not None
    assert credential.source is AuthSource.DOTENV


def test_composite_auth_uses_first_available_provider() -> None:
    class Provider:
        def __init__(self, credential):
            self.credential = credential

        def get_credential(self):
            return self.credential

    expected = AuthCredential("selected-token", AuthSource.ENVIRONMENT)
    ignored = AuthCredential("ignored-token", AuthSource.DOTENV)
    providers = CompositeAuthProvider((Provider(None), Provider(expected), Provider(ignored)))
    assert providers.get_credential() is expected
