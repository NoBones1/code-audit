"""GitHub platform implementation — wraps the existing GitHubClient."""

from __future__ import annotations

from code_audit.github.client import GitHubClient
from code_audit.platforms.base import GitPlatform


class GitHubPlatform(GitPlatform):
    """GitHub integration via the existing REST API client."""

    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self._client = GitHubClient(token=token, base_url=base_url)

    async def get_pr(self, owner: str, repo: str, pr_id: int) -> dict:
        return await self._client.get_pr(owner, repo, pr_id)

    async def get_pr_diff(self, owner: str, repo: str, pr_id: int) -> str:
        return await self._client.get_pr_diff(owner, repo, pr_id)

    async def get_pr_files(self, owner: str, repo: str, pr_id: int) -> list[dict]:
        return await self._client.get_pr_files(owner, repo, pr_id)

    async def post_review(
        self, owner, repo, pr_id, commit_sha, body, comments, event="COMMENT",
    ) -> dict | None:
        return await self._client.create_review(
            owner=owner, repo=repo, pr_number=pr_id,
            body=body, commit_sha=commit_sha,
            comments=comments, event=event,
        )

    async def post_comment(self, owner, repo, pr_id, body) -> dict:
        return await self._client.post_comment(owner, repo, pr_id, body)

    async def create_status(self, owner, repo, sha, state, title, summary, annotations=None) -> dict:
        return await self._client.create_check_run(
            owner=owner, repo=repo,
            name="CodeAudit Review",
            head_sha=sha,
            status="in_progress" if state == "pending" else state,
            output={"title": title, "summary": summary},
        )

    async def update_status(self, owner, repo, status_id, **kwargs) -> dict:
        return await self._client.update_check_run(
            owner=owner, repo=repo, check_run_id=status_id, **kwargs,
        )

    async def close(self) -> None:
        await self._client.close()
