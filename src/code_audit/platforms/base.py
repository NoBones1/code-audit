"""Abstract interface for Git platform integrations."""

from __future__ import annotations

import abc


class GitPlatform(abc.ABC):
    """Abstract base class for Git platform integrations.

    Provides a unified interface for GitHub, GitLab, and Bitbucket
    operations needed for PR-based code review.
    """

    @abc.abstractmethod
    async def get_pr(self, owner: str, repo: str, pr_id: int) -> dict:
        """Fetch pull/merge request metadata."""

    @abc.abstractmethod
    async def get_pr_diff(self, owner: str, repo: str, pr_id: int) -> str:
        """Fetch the raw unified diff for a PR/MR."""

    @abc.abstractmethod
    async def get_pr_files(self, owner: str, repo: str, pr_id: int) -> list[dict]:
        """List changed files in the PR/MR with patch info."""

    @abc.abstractmethod
    async def post_review(
        self,
        owner: str,
        repo: str,
        pr_id: int,
        commit_sha: str,
        body: str,
        comments: list[dict],
        event: str = "COMMENT",
    ) -> dict | None:
        """Post a review with inline comments on specific lines."""

    @abc.abstractmethod
    async def post_comment(self, owner: str, repo: str, pr_id: int, body: str) -> dict:
        """Post a top-level comment on the PR/MR."""

    @abc.abstractmethod
    async def create_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        title: str,
        summary: str,
        annotations: list[dict] | None = None,
    ) -> dict:
        """Create a commit status / check run."""

    @abc.abstractmethod
    async def update_status(
        self,
        owner: str,
        repo: str,
        status_id: int | str,
        **kwargs,
    ) -> dict:
        """Update an existing commit status / check run."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Clean up HTTP client resources."""


# Token environment variable names per platform
TOKEN_ENV_VARS = {
    "github": "GITHUB_TOKEN",
    "gitlab": "GITLAB_TOKEN",
    "bitbucket": "BITBUCKET_TOKEN",
}


class PlatformFactory:
    """Factory for creating platform-specific Git integrations."""

    @staticmethod
    def create(platform: str, token: str, **kwargs) -> GitPlatform:
        """Create a GitPlatform instance by name.

        Args:
            platform: One of "github", "gitlab", "bitbucket".
            token: Authentication token for the platform.
            **kwargs: Additional platform-specific options (e.g., base_url).
        """
        if platform == "github":
            from code_audit.platforms.github import GitHubPlatform
            return GitHubPlatform(token=token, **kwargs)
        elif platform == "gitlab":
            from code_audit.platforms.gitlab import GitLabPlatform
            return GitLabPlatform(token=token, **kwargs)
        elif platform == "bitbucket":
            from code_audit.platforms.bitbucket import BitbucketPlatform
            return BitbucketPlatform(token=token, **kwargs)
        else:
            raise ValueError(f"Unsupported platform: {platform}. Use: github, gitlab, bitbucket")
