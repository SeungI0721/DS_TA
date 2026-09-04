"""Future GitHub REST boundary. Live calls are not implemented in Phase 2."""


class LiveGitHubCallsNotImplementedError(NotImplementedError):
    pass


class GitHubClient:
    def get_repository(self, repository: str) -> dict[str, object]:
        raise LiveGitHubCallsNotImplementedError("Live GitHub calls begin in Phase 4")

    def list_repository_events(self, repository: str) -> list[dict[str, object]]:
        raise LiveGitHubCallsNotImplementedError("Live GitHub calls begin in Phase 4")

    def get_contents(self, repository: str, path: str, ref: str) -> bytes:
        raise LiveGitHubCallsNotImplementedError("Live GitHub calls begin in Phase 4")

    def check_collaborator(self, repository: str, username: str) -> int:
        raise LiveGitHubCallsNotImplementedError("Live GitHub calls begin in Phase 4")

