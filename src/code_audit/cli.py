"""CLI entry point for CodeAudit.

Usage:
    code-audit review                    # Deep review of current changes
    code-audit review --mode quick       # Quick single-agent scan
    code-audit review --mode security    # Security-focused review only
    code-audit review --diff-target main # Review changes vs main branch
    code-audit review --path /project    # Review a specific project
"""

from __future__ import annotations

import asyncio
import os
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from code_audit import __version__

app = typer.Typer(
    name="code-audit",
    help="Multi-agent AI code review tool",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


class ReviewModeChoice(str, Enum):
    quick = "quick"
    deep = "deep"
    security = "security"


@app.command()
def review(
    path: Optional[Path] = typer.Option(
        None,
        "--path", "-p",
        help="Project path to review. Defaults to current directory.",
    ),
    mode: ReviewModeChoice = typer.Option(
        ReviewModeChoice.deep,
        "--mode", "-m",
        help="Review mode: quick (single agent), deep (5 agents + judge), security (security only)",
    ),
    diff_target: str = typer.Option(
        "HEAD",
        "--diff-target", "-d",
        help="Git ref to diff against (branch, commit, or HEAD)",
    ),
    no_sarif: bool = typer.Option(
        False,
        "--no-sarif",
        help="Skip SARIF output generation",
    ),
    no_markdown: bool = typer.Option(
        False,
        "--no-markdown",
        help="Skip markdown report generation",
    ),
) -> None:
    """Run a multi-agent code review on the project."""
    from code_audit.config.loader import load_config
    from code_audit.config.models import OutputFormat, ReviewMode

    project_path = (path or Path.cwd()).resolve()

    if not project_path.is_dir():
        console.print(f"[red]Error: {project_path} is not a directory[/red]")
        raise typer.Exit(1)

    # Map CLI enum to config enum
    mode_map = {
        ReviewModeChoice.quick: ReviewMode.QUICK,
        ReviewModeChoice.deep: ReviewMode.DEEP,
        ReviewModeChoice.security: ReviewMode.SECURITY,
    }

    # Load config with CLI overrides
    config = load_config(
        project_path=project_path,
        mode=mode_map[mode],
        diff_target=diff_target,
    )

    # Apply CLI format overrides
    if no_sarif:
        config.output.formats = [f for f in config.output.formats if f != OutputFormat.SARIF]
    if no_markdown:
        config.output.formats = [f for f in config.output.formats if f != OutputFormat.MARKDOWN]

    # Run the audit
    asyncio.run(_run_audit(config, project_path))


async def _run_audit(config, project_path: Path) -> None:
    """Execute the audit pipeline with terminal output."""
    from code_audit.config.models import OutputFormat
    from code_audit.engine.orchestrator import Orchestrator, SPECIALIST_AGENTS
    from code_audit.output.markdown import write_markdown_report
    from code_audit.output.sarif_writer import write_sarif
    from code_audit.output.terminal import TerminalOutput

    terminal = TerminalOutput()
    terminal.print_header(
        str(project_path),
        config.review.mode.value,
        config.review.diff_target,
    )

    # Determine which agents will run
    if config.review.mode.value == "quick":
        agent_names = ["combined"]
    elif config.review.mode.value == "security":
        agent_names = ["security"]
    else:
        agent_names = [
            name for name in SPECIALIST_AGENTS
            if config.is_agent_enabled(name)
        ]

    # Create orchestrator with terminal callbacks
    orchestrator = Orchestrator(
        config=config,
        project_path=project_path,
        on_agent_start=terminal.on_agent_start,
        on_agent_complete=terminal.on_agent_complete,
        on_agent_error=terminal.on_agent_error,
    )

    # Start progress display
    all_agents = agent_names.copy()
    if config.review.mode.value == "deep":
        all_agents.append("judge")
    terminal.start_progress(all_agents)

    try:
        report = await orchestrator.run()
    except Exception as e:
        terminal.stop_progress()
        console.print(f"\n[red]Audit failed: {e}[/red]")
        raise typer.Exit(1)
    finally:
        terminal.stop_progress()

    # Check for no changes
    if not report.findings and report.summary.files_reviewed == 0:
        terminal.print_no_changes()
        return

    # Print report to terminal
    terminal.print_report(report)

    # Write output files
    output_dir = project_path / config.output.directory
    markdown_path = None
    sarif_path = None

    if OutputFormat.MARKDOWN in config.output.formats:
        markdown_path = output_dir / config.output.markdown_file
        write_markdown_report(report, markdown_path)

    if OutputFormat.SARIF in config.output.formats:
        sarif_path = output_dir / config.output.sarif_file
        write_sarif(report, sarif_path)

    terminal.print_output_paths(
        str(markdown_path) if markdown_path else None,
        str(sarif_path) if sarif_path else None,
    )


@app.command()
def version() -> None:
    """Show the CodeAudit version."""
    console.print(f"CodeAudit v{__version__}")


@app.command()
def init(
    path: Optional[Path] = typer.Option(
        None,
        "--path", "-p",
        help="Project path. Defaults to current directory.",
    ),
) -> None:
    """Initialize CodeAudit configuration for a project.

    Creates audit.config.yaml and REVIEW.md templates.
    """
    project_path = (path or Path.cwd()).resolve()

    # Create audit.config.yaml
    config_path = project_path / "audit.config.yaml"
    if config_path.exists():
        console.print(f"[yellow]{config_path} already exists, skipping[/yellow]")
    else:
        config_path.write_text(_EXAMPLE_CONFIG, encoding="utf-8")
        console.print(f"[green]Created {config_path}[/green]")

    # Create REVIEW.md
    review_path = project_path / "REVIEW.md"
    if review_path.exists():
        console.print(f"[yellow]{review_path} already exists, skipping[/yellow]")
    else:
        review_path.write_text(_EXAMPLE_REVIEW_MD, encoding="utf-8")
        console.print(f"[green]Created {review_path}[/green]")

    console.print("\n[bold]Setup complete![/bold] Edit these files to customize your review rules.")


_EXAMPLE_CONFIG = """\
# CodeAudit Configuration
# See: https://github.com/code-audit/code-audit

llm:
  provider: claude                # claude | gemini | openai_compat
  model: claude-sonnet-4-6
  api_key_env: ANTHROPIC_API_KEY  # Name of the env var containing your API key
  temperature: 0.2

# Per-agent overrides (optional)
# agents:
#   security:
#     llm:
#       model: claude-opus-4-6    # Use strongest model for security
#   judge:
#     llm:
#       provider: gemini
#       model: gemini-2.5-pro
#       api_key_env: GEMINI_API_KEY

review:
  mode: deep                      # quick | deep | security
  include:
    - "**/*"
  exclude:
    - "**/*.test.*"
    - "**/*.spec.*"
    - "node_modules/**"
    - "dist/**"
    - "*.lock"
  max_files: 50

output:
  formats: [terminal, markdown, sarif]
  directory: .audit
"""

_EXAMPLE_REVIEW_MD = """\
# Code Review Guidelines

## Always check
- New API endpoints have corresponding integration tests
- Database migrations are backward-compatible
- Error messages don't leak internal details to users
- Authentication checks are present on protected routes

## Style
- Prefer early returns over nested conditionals
- Use structured logging, not string interpolation in log calls
- Constants should be UPPER_SNAKE_CASE

## Skip
- Generated files under src/gen/
- Formatting-only changes in *.lock files
- Third-party vendored code
"""


@app.command()
def serve(
    port: int = typer.Option(8900, "--port", help="Port for the webhook server"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to (use 0.0.0.0 for external access)"),
) -> None:
    """Start the GitHub webhook server for automatic PR reviews.

    Requires GITHUB_TOKEN env var. Optionally set CODE_AUDIT_WEBHOOK_SECRET
    for signature verification.
    """
    import uvicorn

    from code_audit.github.webhook import create_webhook_app

    if not os.environ.get("GITHUB_TOKEN"):
        console.print("[red]Error: GITHUB_TOKEN environment variable is required[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]CodeAudit Webhook Server[/bold]")
    console.print(f"Listening on http://{host}:{port}/webhook")
    console.print(f"Health check: http://{host}:{port}/health")
    console.print()

    webhook_app = create_webhook_app()
    uvicorn.run(webhook_app, host=host, port=port, log_level="info")


@app.command()
def review_pr(
    repo: str = typer.Argument(help="Repository in owner/name format"),
    pr: int = typer.Argument(help="Pull request number"),
    mode: ReviewModeChoice = typer.Option(
        ReviewModeChoice.deep, "--mode", "-m",
        help="Review mode",
    ),
) -> None:
    """Review a specific GitHub pull request and post findings as comments.

    Requires GITHUB_TOKEN env var with repo permissions.

    Example: code-audit review-pr owner/repo 123
    """
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        console.print("[red]Error: GITHUB_TOKEN environment variable is required[/red]")
        raise typer.Exit(1)

    parts = repo.split("/")
    if len(parts) != 2:
        console.print("[red]Error: repo must be in owner/name format[/red]")
        raise typer.Exit(1)

    owner, repo_name = parts
    mode_map = {
        ReviewModeChoice.quick: ReviewMode.QUICK,
        ReviewModeChoice.deep: ReviewMode.DEEP,
        ReviewModeChoice.security: ReviewMode.SECURITY,
    }

    from code_audit.config.models import ReviewMode
    from code_audit.github.webhook import handle_pr_event
    from code_audit.github.client import GitHubClient

    async def _run():
        client = GitHubClient(token=github_token)
        try:
            pr_data = await client.get_pr(owner, repo_name, pr)
            repo_data = {"owner": {"login": owner}, "name": repo_name, "clone_url": f"https://github.com/{owner}/{repo_name}.git"}
            result = await handle_pr_event(
                action="cli_triggered",
                pr_data=pr_data,
                repo_data=repo_data,
                github_token=github_token,
                review_mode=mode_map[mode],
            )
            console.print(f"[green]Review complete![/green] {result['findings']} findings posted to PR #{pr}")
        finally:
            await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
