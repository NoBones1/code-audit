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

# Load .env file if present (for API keys)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on shell-exported env vars

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
    no_reflect: bool = typer.Option(
        False,
        "--no-reflect",
        help="Skip agent self-reflection pass",
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
    if no_reflect:
        config.review.no_reflect = no_reflect

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
    terminal.print_cost_summary(report)

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

    # Offer auto-fix for findings with suggestions
    fixable = [f for f in report.findings if f.is_fixable]
    if fixable:
        await _offer_fixes(fixable, project_path, config)


async def _offer_fixes(fixable: list, project_path, config) -> None:
    """Interactive fix application — offered after audit completes."""
    from rich.prompt import Prompt
    from rich.syntax import Syntax

    from code_audit.engine.fixer import fix_finding
    from code_audit.llm.fallback import FallbackProvider

    console.print()
    console.print(
        f"[bold]{len(fixable)}[/bold] finding{'s' if len(fixable) != 1 else ''} "
        f"ha{'ve' if len(fixable) != 1 else 's'} suggested fixes.",
    )

    choice = Prompt.ask(
        "Apply fixes?",
        choices=["y", "n", "select"],
        default="n",
    )

    if choice == "n":
        return

    # Determine which findings to fix
    if choice == "select":
        console.print()
        for i, f in enumerate(fixable, 1):
            console.print(
                f"  [bold]{i}[/bold]. {f.severity.emoji} {f.title} "
                f"[dim]({f.location.display})[/dim]"
            )
        console.print()
        selection = Prompt.ask(
            "Enter numbers to apply (comma-separated, e.g. 1,3,5)",
            default="",
        )
        if not selection.strip():
            return
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(",") if x.strip()]
            selected = [fixable[i] for i in indices if 0 <= i < len(fixable)]
        except (ValueError, IndexError):
            console.print("[red]Invalid selection.[/red]")
            return
        if not selected:
            return
    else:
        selected = fixable

    # Create LLM provider for fix generation
    llm = FallbackProvider(config.llm)

    applied = 0
    skipped = 0
    modified_files: set[str] = set()

    for finding in selected:
        console.print()
        console.print(
            f"[bold]{finding.severity.emoji} {finding.title}[/bold] "
            f"[dim]({finding.location.display})[/dim]"
        )

        new_content, diff_str, explanation = await fix_finding(
            finding=finding,
            project_path=project_path,
            llm=llm,
        )

        if new_content is None:
            console.print(f"  [yellow]Skipped: {explanation}[/yellow]")
            skipped += 1
            continue

        # Show diff preview
        console.print(f"  [dim]{explanation}[/dim]")
        console.print()
        if diff_str:
            console.print(Syntax(diff_str, "diff", theme="monokai", line_numbers=False))

        confirm = Prompt.ask("  Apply this fix?", choices=["y", "n"], default="n")
        if confirm == "y":
            file_path = project_path / finding.location.file_path
            file_path.write_text(new_content, encoding="utf-8")
            console.print("  [green]Applied.[/green]")
            applied += 1
            modified_files.add(finding.location.file_path)
        else:
            console.print("  [dim]Skipped.[/dim]")
            skipped += 1

    # Summary
    console.print()
    if applied > 0:
        console.print(
            f"[bold green]Applied {applied} fix{'es' if applied != 1 else ''}[/bold green] "
            f"across {len(modified_files)} file{'s' if len(modified_files) != 1 else ''}. "
            f"{skipped} skipped."
        )
        console.print("[dim]Changes are uncommitted — review and commit when ready.[/dim]")
    else:
        console.print(f"[dim]No fixes applied. {skipped} skipped.[/dim]")


@app.command()
def benchmark(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-finding match details"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output path for results JSON"),
) -> None:
    """Run accuracy benchmarks against known-vulnerable code samples.

    Measures precision, recall, and F1 score by comparing audit findings
    against planted vulnerabilities with known ground truth.
    """
    import asyncio

    from benchmarks.run import main as bench_main

    console.print("[bold]CodeAudit Benchmark Suite[/bold]")
    console.print("[dim]Running deep-mode audit on sample projects with real LLM calls...[/dim]")
    console.print()

    asyncio.run(bench_main(verbose=verbose, output=str(output) if output else None))


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

    # Create REVIEW.md (auto-detect project type for tailored template)
    review_path = project_path / "REVIEW.md"
    if review_path.exists():
        console.print(f"[yellow]{review_path} already exists, skipping[/yellow]")
    else:
        detected = _detect_project_type(project_path)
        review_content = _generate_review_md(detected)
        review_path.write_text(review_content, encoding="utf-8")
        if detected["languages"]:
            console.print(
                f"[green]Created {review_path}[/green] "
                f"(detected: {', '.join(detected['languages'][:4])})"
            )
        else:
            console.print(f"[green]Created {review_path}[/green]")

    console.print("\n[bold]Setup complete![/bold] Edit these files to customize your review rules.")


def _detect_project_type(project_path: Path) -> dict:
    """Detect languages, frameworks, and infrastructure from a project directory."""
    import json

    languages: set[str] = set()
    frameworks: set[str] = set()
    has_docker = False
    has_ci = False

    # Extension → language mapping
    ext_map = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".rb": "Ruby",
        ".php": "PHP",
        ".cs": "C#",
        ".swift": "Swift",
        ".kt": "Kotlin",
    }

    # Scan top-level and one level deep for file extensions
    for p in project_path.iterdir():
        if p.name.startswith("."):
            continue
        if p.is_file():
            lang = ext_map.get(p.suffix.lower())
            if lang:
                languages.add(lang)
        elif p.is_dir() and not p.name.startswith("node_modules"):
            try:
                for child in p.iterdir():
                    if child.is_file():
                        lang = ext_map.get(child.suffix.lower())
                        if lang:
                            languages.add(lang)
            except PermissionError:
                pass

    # Detect Docker
    if (project_path / "Dockerfile").exists() or (project_path / "docker-compose.yml").exists():
        has_docker = True

    # Detect CI
    if (project_path / ".github" / "workflows").is_dir():
        has_ci = True
    elif (project_path / ".gitlab-ci.yml").exists():
        has_ci = True

    # Detect frameworks from package.json
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "react" in all_deps:
                frameworks.add("React")
            if "next" in all_deps:
                frameworks.add("Next.js")
            if "vue" in all_deps:
                frameworks.add("Vue")
            if "express" in all_deps:
                frameworks.add("Express")
            if "angular" in all_deps or "@angular/core" in all_deps:
                frameworks.add("Angular")
            if "svelte" in all_deps:
                frameworks.add("Svelte")
        except (json.JSONDecodeError, OSError):
            pass

    # Detect frameworks from pyproject.toml / requirements.txt
    pyproject = project_path / "pyproject.toml"
    requirements = project_path / "requirements.txt"
    py_deps_text = ""
    if pyproject.exists():
        try:
            py_deps_text = pyproject.read_text(encoding="utf-8").lower()
        except OSError:
            pass
    if requirements.exists():
        try:
            py_deps_text += "\n" + requirements.read_text(encoding="utf-8").lower()
        except OSError:
            pass

    if py_deps_text:
        if "fastapi" in py_deps_text:
            frameworks.add("FastAPI")
        if "django" in py_deps_text:
            frameworks.add("Django")
        if "flask" in py_deps_text:
            frameworks.add("Flask")
        if "sqlalchemy" in py_deps_text:
            frameworks.add("SQLAlchemy")
        if "celery" in py_deps_text:
            frameworks.add("Celery")

    # Detect Go frameworks from go.mod
    go_mod = project_path / "go.mod"
    if go_mod.exists():
        try:
            go_text = go_mod.read_text(encoding="utf-8").lower()
            if "gin-gonic" in go_text:
                frameworks.add("Gin")
            if "gorilla/mux" in go_text:
                frameworks.add("Gorilla Mux")
        except OSError:
            pass

    # Detect Rust frameworks from Cargo.toml
    cargo = project_path / "Cargo.toml"
    if cargo.exists():
        try:
            cargo_text = cargo.read_text(encoding="utf-8").lower()
            if "actix" in cargo_text:
                frameworks.add("Actix")
            if "tokio" in cargo_text:
                frameworks.add("Tokio")
            if "axum" in cargo_text:
                frameworks.add("Axum")
        except OSError:
            pass

    return {
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "has_docker": has_docker,
        "has_ci": has_ci,
    }


def _generate_review_md(detected: dict) -> str:
    """Generate a REVIEW.md template tailored to the detected project type."""
    languages: list[str] = detected.get("languages", [])
    frameworks: list[str] = detected.get("frameworks", [])
    has_docker: bool = detected.get("has_docker", False)
    has_ci: bool = detected.get("has_ci", False)

    lines: list[str] = [
        "# Code Review Guidelines",
        "",
        "## Always check",
        "- New API endpoints have corresponding integration tests",
        "- Database migrations are backward-compatible",
        "- Error messages don't leak internal details to users",
        "- Authentication checks are present on protected routes",
    ]

    # Language-specific rules
    if "Python" in languages:
        lines += [
            "",
            "## Python",
            "- Type hints on public APIs",
            "- No bare except clauses",
            "- Use pathlib instead of os.path for file operations",
            "- Async functions should not block the event loop",
        ]

    if "TypeScript" in languages or "JavaScript" in languages:
        lines += [
            "",
            "## TypeScript / JavaScript",
            "- Strict mode enabled",
            "- No `any` types in production code",
            "- Prefer `const` over `let`; never use `var`",
            "- Async/await over raw promises where possible",
        ]

    if "Go" in languages:
        lines += [
            "",
            "## Go",
            "- Error handling -- never ignore errors",
            "- Context propagation through function chains",
            "- Use `errors.Is` / `errors.As` instead of direct comparison",
            "- Goroutine leaks: ensure goroutines can exit",
        ]

    if "Rust" in languages:
        lines += [
            "",
            "## Rust",
            "- Prefer `Result` over `unwrap()` in library code",
            "- Minimize use of `unsafe` blocks",
            "- Proper lifetime annotations on public APIs",
            "- Use `clippy` lints as guidance",
        ]

    if "Java" in languages:
        lines += [
            "",
            "## Java",
            "- Null safety: use `Optional` over nullable returns",
            "- Close resources with try-with-resources",
            "- Prefer immutable collections where possible",
            "- Follow Java naming conventions strictly",
        ]

    # Framework-specific rules
    if "React" in frameworks:
        lines += [
            "",
            "## React",
            "- Hooks rules compliance (no conditional hooks)",
            "- No direct DOM manipulation",
            "- Memoize expensive computations with useMemo/useCallback",
            "- Key props on list items",
        ]

    if "Next.js" in frameworks:
        lines += [
            "",
            "## Next.js",
            "- Server vs client component boundaries are intentional",
            "- No secrets in client-side code",
            "- Use next/image for images, next/link for navigation",
        ]

    if "Django" in frameworks:
        lines += [
            "",
            "## Django",
            "- CSRF protection on forms",
            "- SQL injection prevention: use ORM queries, no raw SQL",
            "- No secrets in settings.py; use environment variables",
            "- Permission checks on views",
        ]

    if "FastAPI" in frameworks:
        lines += [
            "",
            "## FastAPI",
            "- CSRF protection on forms",
            "- SQL injection prevention via parameterized queries",
            "- Pydantic models for request/response validation",
            "- Dependency injection for shared resources",
        ]

    if "Flask" in frameworks:
        lines += [
            "",
            "## Flask",
            "- CSRF protection on forms",
            "- SQL injection prevention: use parameterized queries",
            "- No secrets in app config; use environment variables",
        ]

    if "Express" in frameworks:
        lines += [
            "",
            "## Express",
            "- Input validation and sanitization on all routes",
            "- Helmet.js or equivalent security headers",
            "- Rate limiting on public endpoints",
        ]

    # Infrastructure rules
    if has_docker:
        lines += [
            "",
            "## Docker",
            "- No secrets in Dockerfiles or docker-compose",
            "- Use multi-stage builds for production images",
            "- Pin base image versions (no `latest` tag)",
        ]

    if has_ci:
        lines += [
            "",
            "## CI/CD",
            "- CI pipeline changes should be reviewed by a second person",
            "- No hardcoded secrets in workflow files",
        ]

    # Standard sections always present
    lines += [
        "",
        "## Style",
        "- Prefer early returns over nested conditionals",
        "- Use structured logging, not string interpolation in log calls",
        "- Constants should be UPPER_SNAKE_CASE",
        "",
        "## Skip",
        "- Generated files under src/gen/",
        "- Formatting-only changes in *.lock files",
        "- Third-party vendored code",
        "",
    ]

    return "\n".join(lines)


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

    if not os.environ.get("CODE_AUDIT_WEBHOOK_SECRET"):
        console.print("[yellow]Warning: CODE_AUDIT_WEBHOOK_SECRET not set — webhook signature verification disabled.[/yellow]")
        console.print("[yellow]Set this env var for production use to prevent unauthorized requests.[/yellow]")
        console.print()

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
    platform: str = typer.Option(
        "github", "--platform",
        help="Git platform: github, gitlab, bitbucket",
    ),
) -> None:
    """Review a pull request / merge request and post findings as comments.

    Supports GitHub, GitLab, and Bitbucket.
    Requires the appropriate token env var (GITHUB_TOKEN, GITLAB_TOKEN, or BITBUCKET_TOKEN).

    Example: code-audit review-pr owner/repo 123 --platform github
    """
    from code_audit.platforms.base import TOKEN_ENV_VARS

    token_env = TOKEN_ENV_VARS.get(platform, "GITHUB_TOKEN")
    token = os.environ.get(token_env, "")
    if not token:
        console.print(f"[red]Error: {token_env} environment variable is required[/red]")
        raise typer.Exit(1)

    if platform not in ("github", "gitlab", "bitbucket"):
        console.print(f"[red]Error: unsupported platform '{platform}'. Use: github, gitlab, bitbucket[/red]")
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
    from code_audit.platforms import PlatformFactory

    clone_urls = {
        "github": f"https://github.com/{owner}/{repo_name}.git",
        "gitlab": f"https://gitlab.com/{owner}/{repo_name}.git",
        "bitbucket": f"https://bitbucket.org/{owner}/{repo_name}.git",
    }

    async def _run():
        platform_client = PlatformFactory.create(platform, token=token)
        try:
            pr_data = await platform_client.get_pr(owner, repo_name, pr)
            repo_data = {
                "owner": {"login": owner},
                "name": repo_name,
                "clone_url": clone_urls.get(platform, clone_urls["github"]),
            }
            result = await handle_pr_event(
                action="cli_triggered",
                pr_data=pr_data,
                repo_data=repo_data,
                github_token=token,
                review_mode=mode_map[mode],
            )
            console.print(f"[green]Review complete![/green] {result['findings']} findings posted to PR #{pr}")
        finally:
            await platform_client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
