"""Bitbucket Cloud platform implementation — PR review via REST API 2.0."""

from __future__ import annotations

import logging

import httpx

from code_audit.platforms.base import GitPlatform

logger = logging.getLogger("code_audit.platforms.bitbucket")


class BitbucketPlatform(GitPlatform):
    """Bitbucket Cloud integration via REST API 2.0.

    Uses Bearer token or app password authentication.
    """

    def __init__(self, token: str, base_url: str = "https://api.bitbucket.org/2.0"):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def get_pr(self, owner: str, repo: str, pr_id: int) -> dict:
        resp = await self._client.get(
            f"/repositories/{owner}/{repo}/pullrequests/{pr_id}",
        )
        resp.raise_for_status()
        return resp.json()

    async def get_pr_diff(self, owner: str, repo: str, pr_id: int) -> str:
        resp = await self._client.get(
            f"/repositories/{owner}/{repo}/pullrequests/{pr_id}/diff",
        )
        resp.raise_for_status()
        return resp.text

    async def get_pr_files(self, owner: str, repo: str, pr_id: int) -> list[dict]:
        resp = await self._client.get(
            f"/repositories/{owner}/{repo}/pullrequests/{pr_id}/diffstat",
        )
        resp.raise_for_status()
        data = resp.json()
        files = []
        for entry in data.get("values", []):
            new_path = entry.get("new", {}).get("path", "")
            old_path = entry.get("old", {}).get("path", "")
            status = entry.get("status", "modified")
            files.append({
                "filename": new_path or old_path,
                "status": status,
                "patch": "",  # Bitbucket diffstat doesn't include patches
            })
        return files

    async def post_review(
        self, owner, repo, pr_id, commit_sha, body, comments, event="COMMENT",
    ) -> dict | None:
        # Post inline comments individually
        for comment in comments:
            try:
                await self._client.post(
                    f"/repositories/{owner}/{repo}/pullrequests/{pr_id}/comments",
                    json={
                        "content": {"raw": comment["body"]},
                        "inline": {
                            "to": comment["line"],
                            "path": comment["path"],
                        },
                    },
                )
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Failed to post inline comment on %s:%d: %s",
                    comment["path"], comment["line"], e,
                )

        # Post the summary as a top-level comment
        if body:
            resp = await self._client.post(
                f"/repositories/{owner}/{repo}/pullrequests/{pr_id}/comments",
                json={"content": {"raw": body}},
            )
            resp.raise_for_status()
            return resp.json()

        return None

    async def post_comment(self, owner, repo, pr_id, body) -> dict:
        resp = await self._client.post(
            f"/repositories/{owner}/{repo}/pullrequests/{pr_id}/comments",
            json={"content": {"raw": body}},
        )
        resp.raise_for_status()
        return resp.json()

    async def create_status(self, owner, repo, sha, state, title, summary, annotations=None) -> dict:
        # Bitbucket states: INPROGRESS, SUCCESSFUL, FAILED, STOPPED
        bb_state = {
            "pending": "INPROGRESS",
            "in_progress": "INPROGRESS",
            "completed": "SUCCESSFUL",
            "success": "SUCCESSFUL",
            "failure": "FAILED",
            "neutral": "SUCCESSFUL",
        }.get(state, "INPROGRESS")

        resp = await self._client.post(
            f"/repositories/{owner}/{repo}/commit/{sha}/statuses/build",
            json={
                "state": bb_state,
                "key": "code-audit",
                "name": "CodeAudit Review",
                "description": f"{title}: {summary}"[:255],
                "url": "",
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def update_status(self, owner, repo, status_id, **kwargs) -> dict:
        # Bitbucket build statuses are updated by re-posting with same key
        sha = kwargs.get("head_sha", "")
        conclusion = kwargs.get("conclusion", "success")
        output = kwargs.get("output", {})
        bb_state = {
            "neutral": "SUCCESSFUL",
            "success": "SUCCESSFUL",
            "failure": "FAILED",
        }.get(conclusion, "SUCCESSFUL")

        resp = await self._client.post(
            f"/repositories/{owner}/{repo}/commit/{sha}/statuses/build",
            json={
                "state": bb_state,
                "key": "code-audit",
                "name": "CodeAudit Review",
                "description": output.get("title", "")[:255],
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
