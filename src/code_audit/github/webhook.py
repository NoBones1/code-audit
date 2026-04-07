"""GitHub webhook receiver — triggers reviews on PR events.

Handles:
- pull_request.opened — triggers review on new PRs
- pull_request.synchronize — triggers review on new pushes to PR
- issue_comment.created — handles @code-audit commands in PR comments
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path

import httpx

from code_audit.config.loader import load_config
from code_audit.config.models import ReviewMode
from code_audit.engine.orchestrator import Orchestrator
from code_audit.github.client import GitHubClient
from code_audit.github.comments import post_review_comments

logger = logging.getLogger("code_audit.webhook")

# ---------------------------------------------------------------------------
# Operational safety
# ---------------------------------------------------------------------------

MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
REVIEW_TIMEOUT_SECONDS = 600  # 10 minutes per review
MAX_CONCURRENT_REVIEWS = 3

_review_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REVIEWS)


class RateLimiter:
    """Simple in-memory sliding-window rate limiter."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}

    def check(self, key: str) -> bool:
        """Return True if the request is allowed, False if rate limited."""
        now = time.monotonic()
        if key not in self._requests:
            self._requests[key] = deque()
        q = self._requests[key]
        # Expire old entries
        while q and q[0] < now - self.window_seconds:
            q.popleft()
        if len(q) >= self.max_requests:
            return False
        q.append(now)
        return True


_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify the GitHub webhook signature (HMAC-SHA256)."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def handle_pr_event(
    action: str,
    pr_data: dict,
    repo_data: dict,
    github_token: str,
    review_mode: ReviewMode = ReviewMode.DEEP,
) -> dict:
    """Handle a pull_request webhook event.

    Clones the repo at the PR head, runs the audit, and posts results.
    """
    owner = repo_data["owner"]["login"]
    repo_name = repo_data["name"]
    pr_number = pr_data["number"]
    head_sha = pr_data["head"]["sha"]
    head_ref = pr_data["head"]["ref"]
    base_ref = pr_data["base"]["ref"]
    clone_url = repo_data["clone_url"]

    review_start = time.monotonic()
    logger.info(
        "PR review started: %s/%s#%d (%s) mode=%s head=%s",
        owner, repo_name, pr_number, action, review_mode.value, head_sha[:12],
    )

    client = GitHubClient(token=github_token)
    check_run_id = None

    try:
        # Create check run to show we're working
        check_run = await client.create_check_run(
            owner=owner,
            repo=repo_name,
            name="CodeAudit Review",
            head_sha=head_sha,
            status="in_progress",
            output={
                "title": "Code review in progress...",
                "summary": f"Running {review_mode.value} mode review on PR #{pr_number}",
            },
        )
        check_run_id = check_run["id"]

        # Clone the repo into a temp directory
        with tempfile.TemporaryDirectory(prefix="code-audit-") as tmpdir:
            project_path = Path(tmpdir) / repo_name

            # Shallow clone with just the PR branch
            subprocess.run(
                [
                    "git", "clone",
                    "--depth", "50",
                    "--branch", head_ref,
                    "--single-branch",
                    clone_url,
                    str(project_path),
                ],
                capture_output=True,
                timeout=120,
                check=True,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_ASKPASS": "echo",
                },
            )

            # Fetch the base branch for diffing
            subprocess.run(
                ["git", "fetch", "origin", base_ref, "--depth", "50"],
                cwd=project_path,
                capture_output=True,
                timeout=60,
            )

            # Load config from the cloned repo
            config = load_config(
                project_path=project_path,
                mode=review_mode,
                diff_target=f"origin/{base_ref}",
            )

            # Run the audit (with concurrency limit + timeout)
            orchestrator = Orchestrator(config=config, project_path=project_path)
            async with _review_semaphore:
                report = await asyncio.wait_for(
                    orchestrator.run(),
                    timeout=REVIEW_TIMEOUT_SECONDS,
                )

        # Post findings as PR review comments
        review_result = await post_review_comments(
            client=client,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            report=report,
        )

        # Update check run with results
        s = report.summary
        conclusion = "neutral"  # Never block merges
        title = f"Found {s.total_findings} findings"
        if s.total_findings == 0:
            title = "No issues found"

        severity_summary = []
        if s.important > 0:
            severity_summary.append(f"🔴 {s.important} Important")
        if s.nit > 0:
            severity_summary.append(f"🟡 {s.nit} Nit")
        if s.pre_existing > 0:
            severity_summary.append(f"🟣 {s.pre_existing} Pre-existing")

        summary_text = " | ".join(severity_summary) if severity_summary else "Clean"

        # Build annotations for the check run
        annotations = []
        for f in report.findings[:50]:  # GitHub limits to 50 annotations per update
            level_map = {"important": "failure", "nit": "warning", "pre_existing": "notice"}
            annotations.append({
                "path": f.location.file_path,
                "start_line": f.location.start_line,
                "end_line": f.location.effective_end_line,
                "annotation_level": level_map.get(f.severity.value, "warning"),
                "title": f.title,
                "message": f.description,
            })

        # Machine-readable severity line
        severity_json = json.dumps({
            "important": s.important,
            "nit": s.nit,
            "pre_existing": s.pre_existing,
        })

        await client.update_check_run(
            owner=owner,
            repo=repo_name,
            check_run_id=check_run_id,
            conclusion=conclusion,
            output={
                "title": title,
                "summary": (
                    f"{summary_text}\n\n"
                    f"Reviewed {s.files_reviewed} files in {report.duration_seconds:.0f}s "
                    f"({report.mode} mode)\n\n"
                    f"<!-- codeaudit-severity: {severity_json} -->"
                ),
                "annotations": annotations,
            },
        )

        duration = time.monotonic() - review_start
        logger.info(
            "PR review completed: %s/%s#%d — %d findings in %.0fs",
            owner, repo_name, pr_number, s.total_findings, duration,
        )

        return {
            "status": "completed",
            "pr_number": pr_number,
            "findings": s.total_findings,
            "check_run_id": check_run_id,
            "duration_seconds": round(duration, 1),
        }

    except asyncio.TimeoutError:
        duration = time.monotonic() - review_start
        logger.error("PR review timed out: %s/%s#%d after %.0fs", owner, repo_name, pr_number, duration)
        if check_run_id is not None:
            try:
                await client.update_check_run(
                    owner=owner,
                    repo=repo_name,
                    check_run_id=check_run_id,
                    conclusion="neutral",
                    output={
                        "title": "Code review timed out",
                        "summary": f"Review exceeded the {REVIEW_TIMEOUT_SECONDS}s time limit.",
                    },
                )
            except Exception:
                pass
        raise

    except Exception as e:
        logger.error("Review failed for PR #%d: %s", pr_number, e)
        # Try to update check run with failure (only if we got a check_run_id)
        if check_run_id is not None:
            try:
                await client.update_check_run(
                    owner=owner,
                    repo=repo_name,
                    check_run_id=check_run_id,
                    conclusion="neutral",
                    output={
                        "title": "Code review encountered an error",
                        "summary": "Review encountered an internal error. Check server logs for details.",
                    },
                )
            except Exception:
                pass
        raise
    finally:
        await client.close()


def parse_review_command(comment_body: str) -> ReviewMode | None:
    """Parse a @code-audit command from a PR comment.

    Supported commands:
        @code-audit review          → deep mode
        @code-audit review quick    → quick mode
        @code-audit review deep     → deep mode
        @code-audit review security → security mode
    """
    body = comment_body.strip().lower()

    if "@code-audit review" not in body and "@code-audit" not in body:
        return None

    if "quick" in body:
        return ReviewMode.QUICK
    elif "security" in body:
        return ReviewMode.SECURITY
    else:
        return ReviewMode.DEEP


def _detect_platform(headers: dict) -> str:
    """Detect the Git platform from webhook request headers."""
    if "x-github-event" in {k.lower() for k in headers.keys()}:
        return "github"
    if "x-gitlab-event" in {k.lower() for k in headers.keys()}:
        return "gitlab"
    if "x-event-key" in {k.lower() for k in headers.keys()}:
        return "bitbucket"
    return "github"  # default


def _verify_gitlab_token(headers: dict, secret: str) -> bool:
    """GitLab uses a simple shared token in the X-Gitlab-Token header."""
    token = headers.get("X-Gitlab-Token", "")
    return hmac.compare_digest(token, secret)


def _parse_gitlab_event(data: dict, headers: dict) -> tuple[str, dict | None, dict | None]:
    """Parse a GitLab webhook payload into (action, mr_data, project_data)."""
    event = headers.get("X-Gitlab-Event", "")
    attrs = data.get("object_attributes", {})

    if "Merge Request" in event:
        action = attrs.get("action", "")  # open, update, merge, close
        if action in ("open", "update", "reopen"):
            mr_data = {
                "number": attrs.get("iid"),
                "head": {"sha": attrs.get("last_commit", {}).get("id", ""), "ref": attrs.get("source_branch", "")},
                "base": {"ref": attrs.get("target_branch", "")},
                "draft": attrs.get("work_in_progress", False),
            }
            project = data.get("project", {})
            repo_data = {
                "owner": {"login": project.get("namespace", "")},
                "name": project.get("name", ""),
                "clone_url": project.get("git_http_url", ""),
            }
            return action, mr_data, repo_data

    if "Note" in event and attrs.get("noteable_type") == "MergeRequest":
        comment_body = attrs.get("note", "")
        mode = parse_review_command(comment_body)
        if mode is not None:
            mr = data.get("merge_request", {})
            mr_data = {
                "number": mr.get("iid"),
                "head": {"sha": mr.get("last_commit", {}).get("id", ""), "ref": mr.get("source_branch", "")},
                "base": {"ref": mr.get("target_branch", "")},
                "draft": mr.get("work_in_progress", False),
            }
            project = data.get("project", {})
            repo_data = {
                "owner": {"login": project.get("namespace", "")},
                "name": project.get("name", ""),
                "clone_url": project.get("git_http_url", ""),
            }
            return "comment_triggered", mr_data, repo_data

    return "", None, None


def _parse_bitbucket_event(data: dict, headers: dict) -> tuple[str, dict | None, dict | None]:
    """Parse a Bitbucket webhook payload into (action, pr_data, repo_data)."""
    event_key = headers.get("X-Event-Key", "")

    if event_key.startswith("pullrequest:"):
        action = event_key.split(":")[-1]  # created, updated, etc.
        if action in ("created", "updated"):
            pr = data.get("pullrequest", {})
            source = pr.get("source", {})
            dest = pr.get("destination", {})
            pr_data = {
                "number": pr.get("id"),
                "head": {"sha": source.get("commit", {}).get("hash", ""), "ref": source.get("branch", {}).get("name", "")},
                "base": {"ref": dest.get("branch", {}).get("name", "")},
                "draft": False,
            }
            repo = data.get("repository", {})
            owner = repo.get("owner", {})
            links = repo.get("links", {})
            clone_url = ""
            for link in links.get("clone", []):
                if link.get("name") == "https":
                    clone_url = link.get("href", "")
                    break
            repo_data = {
                "owner": {"login": owner.get("username", owner.get("display_name", ""))},
                "name": repo.get("name", ""),
                "clone_url": clone_url,
            }
            return action, pr_data, repo_data

    return "", None, None


def create_webhook_app():
    """Create the FastAPI app for receiving webhooks from GitHub, GitLab, and Bitbucket.

    Returns a FastAPI application that can be run with uvicorn.
    Platform is auto-detected from request headers.
    """
    from fastapi import FastAPI, Request, HTTPException, BackgroundTasks

    app = FastAPI(title="CodeAudit Webhook", version="0.1.0")

    webhook_secret = os.environ.get("CODE_AUDIT_WEBHOOK_SECRET", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    gitlab_token = os.environ.get("GITLAB_TOKEN", "")
    bitbucket_token = os.environ.get("BITBUCKET_TOKEN", "")

    if not webhook_secret:
        logger.warning(
            "CODE_AUDIT_WEBHOOK_SECRET not set — webhook signature verification disabled. "
            "Set this env var for production use."
        )

    @app.post("/webhook")
    async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
        """Receive and process webhook events from GitHub, GitLab, or Bitbucket."""

        # Rate limiting by client IP
        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.check(client_ip):
            raise HTTPException(429, "Too many requests")

        payload = await request.body()

        # Payload size check
        if len(payload) > MAX_PAYLOAD_SIZE:
            raise HTTPException(413, "Payload too large")

        # Detect platform from headers
        platform = _detect_platform(dict(request.headers))

        # Platform-specific signature verification
        if platform == "github" and webhook_secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not verify_signature(payload, signature, webhook_secret):
                raise HTTPException(401, "Unauthorized")
        elif platform == "gitlab" and webhook_secret:
            if not _verify_gitlab_token(dict(request.headers), webhook_secret):
                raise HTTPException(401, "Unauthorized")
        elif platform == "bitbucket" and webhook_secret:
            signature = request.headers.get("X-Hub-Signature", "")
            if not verify_signature(payload, signature, webhook_secret):
                raise HTTPException(401, "Unauthorized")

        # Resolve token for this platform
        token = {"github": github_token, "gitlab": gitlab_token, "bitbucket": bitbucket_token}.get(platform, "")
        if not token:
            raise HTTPException(500, f"{platform.upper()}_TOKEN not configured")

        data = json.loads(payload)

        # Platform-specific event parsing
        if platform == "github":
            return await _handle_github_webhook(data, request.headers, token, background_tasks)
        elif platform == "gitlab":
            action, mr_data, repo_data = _parse_gitlab_event(data, dict(request.headers))
            if mr_data and repo_data:
                if mr_data.get("draft", False):
                    return {"status": "skipped", "reason": "draft MR"}
                background_tasks.add_task(
                    handle_pr_event,
                    action=action, pr_data=mr_data, repo_data=repo_data,
                    github_token=token,
                )
                return {"status": "queued", "platform": "gitlab", "mr": mr_data.get("number")}
        elif platform == "bitbucket":
            action, pr_data, repo_data = _parse_bitbucket_event(data, dict(request.headers))
            if pr_data and repo_data:
                background_tasks.add_task(
                    handle_pr_event,
                    action=action, pr_data=pr_data, repo_data=repo_data,
                    github_token=token,
                )
                return {"status": "queued", "platform": "bitbucket", "pr": pr_data.get("number")}

        return {"status": "ignored", "platform": platform}

    async def _handle_github_webhook(data, headers, token, background_tasks):
        """Handle GitHub-specific webhook events (preserves existing behavior)."""
        event = headers.get("X-GitHub-Event", "")

        if event == "pull_request":
            action = data.get("action", "")
            if action in ("opened", "synchronize", "ready_for_review"):
                pr_data = data["pull_request"]
                if pr_data.get("draft", False):
                    return {"status": "skipped", "reason": "draft PR"}

                background_tasks.add_task(
                    handle_pr_event,
                    action=action, pr_data=pr_data,
                    repo_data=data["repository"], github_token=token,
                )
                return {"status": "queued", "pr": pr_data["number"]}

        elif event == "issue_comment":
            action = data.get("action", "")
            if action == "created" and "pull_request" in data.get("issue", {}):
                comment_body = data["comment"]["body"]
                mode = parse_review_command(comment_body)
                if mode is not None:
                    pr_url = data["issue"]["pull_request"]["url"]
                    async with httpx.AsyncClient(
                        headers={
                            "Authorization": f"token {token}",
                            "Accept": "application/vnd.github.v3+json",
                        }
                    ) as http:
                        resp = await http.get(pr_url)
                        resp.raise_for_status()
                        pr_data = resp.json()

                    background_tasks.add_task(
                        handle_pr_event,
                        action="comment_triggered", pr_data=pr_data,
                        repo_data=data["repository"], github_token=token,
                        review_mode=mode,
                    )
                    return {"status": "queued", "mode": mode.value}

        return {"status": "ignored", "event": event}

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "code-audit-webhook"}

    return app
