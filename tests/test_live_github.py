from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from github_lab_grader.auth import default_auth_provider
from github_lab_grader.github_client import GitHubClient, GitHubClientSettings


@pytest.mark.live
def test_authorized_repository_read_only_smoke() -> None:
    local_values = dotenv_values(".env")
    run_live = os.environ.get("RUN_GITHUB_LIVE_TESTS") or local_values.get(
        "RUN_GITHUB_LIVE_TESTS"
    )
    if run_live != "1":
        pytest.skip("RUN_GITHUB_LIVE_TESTS=1 is required")
    repository = (
        os.environ.get("GITHUB_LIVE_REPOSITORY")
        or local_values.get("GITHUB_LIVE_REPOSITORY")
        or ""
    ).strip()
    if not repository:
        pytest.skip("GITHUB_LIVE_REPOSITORY is required")
    credential = default_auth_provider().get_credential()
    if credential is None:
        pytest.skip("GitHub authentication is unavailable")

    config = json.loads(Path("config.json").read_text(encoding="utf-8"))
    api = GitHubClient(GitHubClientSettings.from_global_config(config), credential)
    assert api.get_authenticated_user()
    metadata = api.get_repository(repository)
    events = api.list_repository_events(repository)
    entries, _rate_limit = api.get_root_contents_at_ref(repository, metadata.default_branch)
    assert isinstance(entries, tuple)
    if events.push_events:
        api.get_readme_at_sha(repository, events.push_events[0].head_sha)
