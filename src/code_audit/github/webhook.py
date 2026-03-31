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
import subprocess
import tempfile
from pathlib import Path

from code_audit.config.loader import load_config
from code_audit.config.models import ReviewMode
from code_audit.engine.orchestrator import Orchestrator
from code_audit.github.client import GitHubClient
from code_audit.github.comments import post_review_comments

logger = logging.getLogger("code_audit.webhook")


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

    logger.info(
        f"Processing PR #{pr_number} ({action}) on {owner}/{repo_name}: "
        f"{base_ref}...{head_ref}"
    )

    client = GitHubClient(token=github_token)

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

            # Run the audit
            orchestrator = Orchestrator(config=config, project_path=project_path)
            report = await orchestrator.run()

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

        return {
            "status": "completed",
            "pr_number": pr_number,
            "findings": s.total_findings,
            "check_run_id": check_run_id,
        }

    except Exception as e:
        logger.error(f"Review failed for PR #{pr_number}: {e}")
        # Try to update check run with failure
        try:
            await client.update_check_run(
                owner=owner,
                repo=repo_name,
                check_run_id=check_run_id,
                conclusion="neutral",
                output={
                    "title": "Code review encountered an error",
                    "summary": f"Error: {str(e)[:500]}",
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


def create_webhook_app():
    """Create the FastAPI app for receiving GitHub webhooks.

    Returns a FastAPI application that can be run with uvicorn.
    """
    from fastapi import FastAPI, Request, HTTPException, BackgroundTasks

    app = FastAPI(title="CodeAudit Webhook", version="0.1.0")

    webhook_secret = os.environ.get("CODE_AUDIT_WEBHOOK_SECRET", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    @app.post("/webhook")
    async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
        """Receive and process GitHub webhook events."""
        if not github_token:
            raise HTTPException(500, "GITHUB_TOKEN not configured")

        payload = await request.body()

        # Verify signature if secret is configured
        if webhook_secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not verify_signature(payload, signature, webhook_secret):
                raise HTTPException(401, "Invalid signature")

        event = request.headers.get("X-GitHub-Event", "")
        data = json.loads(payload)

        if event == "pull_request":
            action = data.get("action", "")
            if action in ("opened", "synchronize", "ready_for_review"):
                pr_data = data["pull_request"]
                # Skip draft PRs unless explicitly requested
                if pr_data.get("draft", False):
                    return {"status": "skipped", "reason": "draft PR"}

                background_tasks.add_task(
                    handle_pr_event,
                    action=action,
                    pr_data=pr_data,
                    repo_data=data["repository"],
                    github_token=github_token,
                )
                return {"status": "queued", "pr": pr_data["number"]}

        elif event == "issue_comment":
            action = data.get("action", "")
            if action == "created" and "pull_request" in data.get("issue", {}):
                comment_body = data["comment"]["body"]
                mode = parse_review_command(comment_body)
                if mode is not None:
                    # Fetch full PR data
                    pr_url = data["issue"]["pull_request"]["url"]
                    async with httpx.AsyncClient(
                        headers={
                            "Authorization": f"token {github_token}",
                            "Accept": "application/vnd.github.v3+json",
                        }
                    ) as http:
                        resp = await http.get(pr_url)
                        resp.raise_for_status()
                        pr_data = resp.json()

                    background_tasks.add_task(
                        handle_pr_event,
                        action="comment_triggered",
                        pr_data=pr_data,
                        repo_data=data["repository"],
                        github_token=github_token,
                        review_mode=mode,
                    )
                    return {"status": "queued", "mode": mode.value}

        return {"status": "ignored", "event": event}

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "code-audit-webhook"}

    return app
