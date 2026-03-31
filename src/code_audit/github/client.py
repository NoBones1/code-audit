"""GitHub API client for posting reviews, comments, and check runs.

Supports two auth modes:
1. GitHub App (JWT + installation token) — for the webhook service
2. Personal Access Token — for CLI and GitHub Actions usage
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class GitHubClient:
    """Thin wrapper around the GitHub REST API v3."""

    token: str = ""
    base_url: str = "https://api.github.com"
    _client: httpx.AsyncClient = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not self.token:
            self.token = os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN env var or pass token directly."
            )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    # ── Pull Request Info ──────────────────────────────────────────

    async def get_pr(self, owner: str, repo: str, pr_number: int) -> dict:
        """Get pull request details."""
        resp = await self._client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        resp.raise_for_status()
        return resp.json()

    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Get the raw diff for a pull request."""
        resp = await self._client.get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        resp.raise_for_status()
        return resp.text

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """Get the list of files changed in a PR."""
        files = []
        page = 1
        while True:
            resp = await self._client.get(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            files.extend(batch)
            page += 1
        return files

    async def get_file_content(
        self, owner: str, repo: str, path: str, ref: str
    ) -> str | None:
        """Get the content of a file at a specific ref."""
        resp = await self._client.get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.v3.raw"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    # ── Reviews & Comments ─────────────────────────────────────────

    async def create_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        comments: list[dict],
        event: str = "COMMENT",
    ) -> dict:
        """Create a pull request review with inline comments.

        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number
            commit_sha: The SHA of the commit to review
            body: Top-level review body text
            comments: List of inline comment dicts with keys:
                - path: file path
                - line: line number in the diff (new file side)
                - body: comment text
            event: APPROVE, REQUEST_CHANGES, or COMMENT
        """
        resp = await self._client.post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            json={
                "commit_id": commit_sha,
                "body": body,
                "event": event,
                "comments": comments,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def post_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict:
        """Post a top-level comment on a PR/issue."""
        resp = await self._client.post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()

    # ── Check Runs ─────────────────────────────────────────────────

    async def create_check_run(
        self,
        owner: str,
        repo: str,
        name: str,
        head_sha: str,
        status: str = "in_progress",
        output: dict | None = None,
        conclusion: str | None = None,
    ) -> dict:
        """Create or update a check run (for the Checks tab)."""
        payload: dict = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }
        if output:
            payload["output"] = output
        if conclusion:
            payload["conclusion"] = conclusion
            payload["status"] = "completed"

        resp = await self._client.post(
            f"/repos/{owner}/{repo}/check-runs",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def update_check_run(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        status: str | None = None,
        conclusion: str | None = None,
        output: dict | None = None,
    ) -> dict:
        """Update an existing check run."""
        payload: dict = {}
        if status:
            payload["status"] = status
        if conclusion:
            payload["conclusion"] = conclusion
            payload["status"] = "completed"
        if output:
            payload["output"] = output

        resp = await self._client.patch(
            f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    # ── SARIF Upload ───────────────────────────────────────────────

    async def upload_sarif(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
        ref: str,
        sarif_content: str,
    ) -> dict:
        """Upload a SARIF file to GitHub Code Scanning."""
        import base64
        import gzip

        compressed = gzip.compress(sarif_content.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("ascii")

        resp = await self._client.post(
            f"/repos/{owner}/{repo}/code-scanning/sarifs",
            json={
                "commit_sha": commit_sha,
                "ref": ref,
                "sarif": encoded,
            },
        )
        resp.raise_for_status()
        return resp.json()
