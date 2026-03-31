"""Rich terminal output -- live progress panels, severity-colored findings."""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from code_audit.models.finding import Severity
from code_audit.models.report import AuditReport

console = Console()

SEVERITY_STYLES = {
    Severity.IMPORTANT: "bold red",
    Severity.NIT: "bold yellow",
    Severity.PRE_EXISTING: "bold magenta",
}

SEVERITY_ICONS = {
    Severity.IMPORTANT: "🔴",
    Severity.NIT: "🟡",
    Severity.PRE_EXISTING: "🟣",
}

AGENT_ICONS = {
    "security": "🔒",
    "architectural": "🏗️ ",
    "performance": "⚡",
    "functional": "✅",
    "maintainability": "📐",
    "combined": "🔍",
    "judge": "⚖️ ",
}


class TerminalOutput:
    """Manages Rich terminal output for the audit lifecycle."""

    def __init__(self):
        self.console = console
        self._progress: Progress | None = None
        self._live: Live | None = None
        self._agent_tasks: dict[str, int] = {}

    def print_header(self, project_path: str, mode: str, diff_target: str) -> None:
        """Print the audit header."""
        self.console.print()
        self.console.print(
            Panel(
                f"[bold]CodeAudit[/bold] — Multi-Agent Code Review\n"
                f"Project: [cyan]{project_path}[/cyan]\n"
                f"Mode: [green]{mode}[/green] | Diff target: [yellow]{diff_target}[/yellow]",
                border_style="blue",
            )
        )

    def print_context_summary(
        self,
        files_changed: int,
        languages: list[str],
        total_additions: int,
        total_deletions: int,
        has_review_rules: bool,
    ) -> None:
        """Print the context gathering summary."""
        self.console.print(f"\n  Files changed: [bold]{files_changed}[/bold]")
        self.console.print(f"  Languages: {', '.join(languages) if languages else 'unknown'}")
        self.console.print(f"  Changes: [green]+{total_additions}[/green] / [red]-{total_deletions}[/red]")
        if has_review_rules:
            self.console.print("  REVIEW.md: [green]loaded[/green]")
        self.console.print()

    def start_progress(self, agent_names: list[str]) -> None:
        """Start the live progress display for parallel agents."""
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
        )
        for name in agent_names:
            icon = AGENT_ICONS.get(name, "🤖")
            task_id = self._progress.add_task(f"{icon} {name}", total=None)
            self._agent_tasks[name] = task_id
        self._live = Live(self._progress, console=self.console, refresh_per_second=4)
        self._live.start()

    def on_agent_start(self, name: str) -> None:
        """Called when an agent starts reviewing."""
        if self._progress and name in self._agent_tasks:
            icon = AGENT_ICONS.get(name, "🤖")
            self._progress.update(
                self._agent_tasks[name],
                description=f"{icon} {name} [dim]reviewing...[/dim]",
            )

    def on_agent_complete(self, name: str, finding_count: int, duration: float) -> None:
        """Called when an agent completes its review."""
        if self._progress and name in self._agent_tasks:
            icon = AGENT_ICONS.get(name, "🤖")
            color = "green" if finding_count == 0 else "yellow"
            self._progress.update(
                self._agent_tasks[name],
                description=(
                    f"{icon} {name} [{color}]{finding_count} findings[/{color}] "
                    f"[dim]({duration:.1f}s)[/dim]"
                ),
                completed=True,
                total=1,
            )

    def on_agent_error(self, name: str, error: str) -> None:
        """Called when an agent fails."""
        if self._progress and name in self._agent_tasks:
            icon = AGENT_ICONS.get(name, "🤖")
            self._progress.update(
                self._agent_tasks[name],
                description=f"{icon} {name} [red]FAILED: {error[:50]}[/red]",
                completed=True,
                total=1,
            )

    def stop_progress(self) -> None:
        """Stop the live progress display."""
        if self._live:
            self._live.stop()
            self._live = None

    def print_report(self, report: AuditReport) -> None:
        """Print the final audit report to the terminal."""
        self.console.print()

        # Summary panel
        summary = report.summary
        if summary.total_findings == 0:
            self.console.print(
                Panel(
                    "[bold green]No issues found![/bold green] The code looks clean.",
                    title="Audit Complete",
                    border_style="green",
                )
            )
        else:
            summary_parts = []
            if summary.important > 0:
                summary_parts.append(f"🔴 {summary.important} Important")
            if summary.nit > 0:
                summary_parts.append(f"🟡 {summary.nit} Nit")
            if summary.pre_existing > 0:
                summary_parts.append(f"🟣 {summary.pre_existing} Pre-existing")

            self.console.print(
                Panel(
                    f"[bold]{summary.total_findings} findings[/bold] across "
                    f"{summary.files_reviewed} files\n"
                    + " | ".join(summary_parts)
                    + f"\nDuration: {report.duration_seconds:.1f}s",
                    title="Audit Complete",
                    border_style="red" if summary.important > 0 else "yellow",
                )
            )

        # Findings table
        if report.findings:
            self.console.print()
            table = Table(title="Findings", show_lines=True, padding=(0, 1))
            table.add_column("Severity", width=12)
            table.add_column("Location", style="cyan", min_width=25)
            table.add_column("Issue", min_width=40)
            table.add_column("Confidence", width=10, justify="right")

            for finding in report.findings:
                severity_text = Text(
                    f"{SEVERITY_ICONS[finding.severity]} {finding.severity.label}",
                    style=SEVERITY_STYLES[finding.severity],
                )
                table.add_row(
                    severity_text,
                    finding.location.display,
                    finding.title,
                    f"{finding.confidence:.0%}",
                )

            self.console.print(table)

        # Detailed findings
        if report.findings:
            self.console.print("\n[bold]Details[/bold]\n")
            for i, finding in enumerate(report.findings, 1):
                icon = SEVERITY_ICONS[finding.severity]
                style = SEVERITY_STYLES[finding.severity]

                self.console.print(
                    f"  {icon} [bold][{style}]{finding.title}[/{style}][/bold]"
                )
                self.console.print(f"     [dim]{finding.location.display}[/dim] | {finding.dimension}")
                self.console.print(f"     {finding.description}")
                if finding.suggestion:
                    self.console.print(f"     [green]Suggestion:[/green] {finding.suggestion}")
                self.console.print()

    def print_output_paths(self, markdown_path: str | None, sarif_path: str | None) -> None:
        """Print paths to generated output files."""
        self.console.print("[dim]Output files:[/dim]")
        if markdown_path:
            self.console.print(f"  📄 Markdown: [cyan]{markdown_path}[/cyan]")
        if sarif_path:
            self.console.print(f"  📊 SARIF: [cyan]{sarif_path}[/cyan]")
        self.console.print()

    def print_no_changes(self) -> None:
        """Print message when no changes are detected."""
        self.console.print(
            Panel(
                "[yellow]No code changes detected.[/yellow]\n"
                "Make sure you have uncommitted changes or specify a diff target.",
                title="Nothing to Review",
                border_style="yellow",
            )
        )
