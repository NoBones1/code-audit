"""GitLab platform implementation — Merge Request review via REST API v4."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from code_audit.platforms.base import GitPlatform

logger = logging.getLogger("code_audit.platforms.gitlab")


class GitLabPlatform(GitPlatform):
    """GitLab integration via REST API v4.

    Uses PRIVATE-TOKEN authentication.
    Supports self-hosted instances via base_url.
    """

    def __init__(self, token: str, base_url: str = "https://gitlab.com/api/v4"):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "PRIVATE-TOKEN": token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _project_id(self, owner: str, repo: str) -> str:
        """URL-encode owner/repo as GitLab project ID."""
        return quote(f"{owner}/{repo}", safe="")

    async def get_pr(self, owner: str, repo: str, pr_id: int) -> dict:
        pid = self._project_id(owner, repo)
        resp = await self._client.get(f"/projects/{pid}/merge_requests/{pr_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_pr_diff(self, owner: str, repo: str, pr_id: int) -> str:
        pid = self._project_id(owner, repo)
        resp = await self._client.get(
            f"/projects/{pid}/merge_requests/{pr_id}/changes",
        )
        resp.raise_for_status()
        data = resp.json()
        # Reconstruct unified diff from changes array
        parts: list[str] = []
        for change in data.get("changes", []):
            parts.append(change.get("diff", ""))
        return "\n".join(parts)

    async def get_pr_files(self, owner: str, repo: str, pr_id: int) -> list[dict]:
        pid = self._project_id(owner, repo)
        resp = await self._client.get(
            f"/projects/{pid}/merge_requests/{pr_id}/changes",
        )
        resp.raise_for_status()
        data = resp.json()
        files = []
        for change in data.get("changes", []):
            files.append({
                "filename": change.get("new_path", change.get("old_path", "")),
                "status": "renamed" if change.get("renamed_file") else (
                    "added" if change.get("new_file") else (
                        "removed" if change.get("deleted_file") else "modified"
                    )
                ),
                "patch": change.get("diff", ""),
            })
        return files

    async def post_review(
        self, owner, repo, pr_id, commit_sha, body, comments, event="COMMENT",
    ) -> dict | None:
        pid = self._project_id(owner, repo)

        # Post inline comments as discussions with position
        mr = await self.get_pr(owner, repo, pr_id)
        base_sha = mr.get("diff_refs", {}).get("base_sha", "")
        head_sha = mr.get("diff_refs", {}).get("head_sha", commit_sha)
        start_sha = mr.get("diff_refs", {}).get("start_sha", base_sha)

        for comment in comments:
            try:
                await self._client.post(
                    f"/projects/{pid}/merge_requests/{pr_id}/discussions",
                    json={
                        "body": comment["body"],
                        "position": {
                            "position_type": "text",
                            "base_sha": base_sha,
                            "head_sha": head_sha,
                            "start_sha": start_sha,
                            "new_path": comment["path"],
                            "new_line": comment["line"],
                        },
                    },
                )
            except httpx.HTTPStatusError as e:
                logger.warning("Failed to post inline comment on %s:%d: %s", comment["path"], comment["line"], e)

        # Post the summary as a top-level note
        if body:
            resp = await self._client.post(
                f"/projects/{pid}/merge_requests/{pr_id}/notes",
                json={"body": body},
            )
            resp.raise_for_status()
            return resp.json()

        return None

    async def post_comment(self, owner, repo, pr_id, body) -> dict:
        pid = self._project_id(owner, repo)
        resp = await self._client.post(
            f"/projects/{pid}/merge_requests/{pr_id}/notes",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()

    async def create_status(self, owner, repo, sha, state, title, summary, annotations=None) -> dict:
        pid = self._project_id(owner, repo)
        # GitLab states: pending, running, success, failed, canceled
        gl_state = {"pending": "running", "in_progress": "running", "completed": "success"}.get(state, state)
        resp = await self._client.post(
            f"/projects/{pid}/statuses/{sha}",
            json={
                "state": gl_state,
                "name": "CodeAudit Review",
                "description": f"{title}: {summary}"[:255],
                "target_url": "",
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def update_status(self, owner, repo, status_id, **kwargs) -> dict:
        # GitLab doesn't have updatable check runs — create a new status
        sha = kwargs.get("head_sha", "")
        conclusion = kwargs.get("conclusion", "success")
        output = kwargs.get("output", {})
        gl_state = {"neutral": "success", "success": "success", "failure": "failed"}.get(conclusion, conclusion)
        pid = self._project_id(owner, repo)
        resp = await self._client.post(
            f"/projects/{pid}/statuses/{sha}",
            json={
                "state": gl_state,
                "name": "CodeAudit Review",
                "description": output.get("title", "")[:255],
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
