"""Benchmark runner — measures code-audit accuracy against known-vulnerable samples.

Usage:
    python benchmarks/run.py [--verbose] [--output results.json]
    code-audit benchmark [--verbose] [--output results.json]

Runs each sample project through a full deep-mode audit, then compares
findings against ground truth to calculate precision, recall, and F1.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# Ensure the project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GroundTruthEntry:
    file_path: str
    start_line: int
    dimension: str = ""
    cwe: str = ""
    title_pattern: str = ""
    severity: str = ""


@dataclass
class MatchResult:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass
class ProjectResult:
    name: str
    match: MatchResult = field(default_factory=MatchResult)
    duration_seconds: float = 0.0
    finding_count: int = 0
    expected_count: int = 0
    matched_entries: list[str] = field(default_factory=list)
    unmatched_predictions: list[str] = field(default_factory=list)
    missed_entries: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Git setup for sample projects
# ---------------------------------------------------------------------------


def _setup_git_repo(sample_dir: Path, work_dir: Path) -> None:
    """Copy sample files into a temp dir with a git repo and initial commit."""
    # Copy all sample files
    for item in sample_dir.iterdir():
        if item.name == "ground_truth.json":
            continue
        dest = work_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Init git repo with all files as "new changes"
    env = {**os.environ, "GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@test",
           "GIT_COMMITTER_NAME": "bench", "GIT_COMMITTER_EMAIL": "bench@test"}
    subprocess.run(["git", "init"], cwd=work_dir, capture_output=True, check=True, env=env)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=work_dir, capture_output=True, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=work_dir, capture_output=True, check=True, env=env)


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

LINE_TOLERANCE = 3


def _match_findings(findings: list, ground_truth: list[GroundTruthEntry]) -> MatchResult:
    """Match predicted findings against ground truth entries.

    A finding matches if:
    - file_path matches exactly
    - start_line is within ±LINE_TOLERANCE
    - title_pattern appears in finding title (case-insensitive), if specified
    """
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()

    for gi, gt in enumerate(ground_truth):
        for fi, finding in enumerate(findings):
            if fi in matched_pred:
                continue

            # File path must match
            if finding.location.file_path != gt.file_path:
                continue

            # Line must be within tolerance
            if abs(finding.location.start_line - gt.start_line) > LINE_TOLERANCE:
                continue

            # Title pattern must match (if specified)
            if gt.title_pattern and gt.title_pattern.lower() not in finding.title.lower():
                continue

            # Match found
            matched_gt.add(gi)
            matched_pred.add(fi)
            break

    tp = len(matched_gt)
    fp = len(findings) - len(matched_pred)
    fn = len(ground_truth) - len(matched_gt)

    return MatchResult(tp=tp, fp=fp, fn=fn)


# ---------------------------------------------------------------------------
# Core benchmark runner
# ---------------------------------------------------------------------------


async def run_benchmark(verbose: bool = False) -> list[ProjectResult]:
    """Run all benchmark samples and return results."""
    from code_audit.config.loader import load_config
    from code_audit.config.models import ReviewMode
    from code_audit.engine.orchestrator import Orchestrator

    results: list[ProjectResult] = []

    sample_dirs = sorted(
        [d for d in SAMPLES_DIR.iterdir() if d.is_dir() and (d / "ground_truth.json").exists()]
    )

    if not sample_dirs:
        print("No benchmark samples found in", SAMPLES_DIR)
        return results

    for sample_dir in sample_dirs:
        name = sample_dir.name

        # Load ground truth
        gt_data = json.loads((sample_dir / "ground_truth.json").read_text())
        gt_entries = [GroundTruthEntry(**e) for e in gt_data["expected_findings"]]

        if verbose:
            print(f"\n{'='*60}")
            print(f"Running: {name} ({len(gt_entries)} expected findings)")
            print(f"{'='*60}")

        # Setup temp git repo
        tmpdir = tempfile.mkdtemp(prefix=f"bench_{name}_")
        work_path = Path(tmpdir)

        try:
            _setup_git_repo(sample_dir, work_path)

            # Run full audit
            config = load_config(project_path=work_path, mode=ReviewMode.DEEP)
            orchestrator = Orchestrator(config=config, project_path=work_path)

            start = time.monotonic()
            report = await orchestrator.run()
            duration = time.monotonic() - start

            # Match findings
            match = _match_findings(report.findings, gt_entries)

            pr = ProjectResult(
                name=name,
                match=match,
                duration_seconds=duration,
                finding_count=len(report.findings),
                expected_count=len(gt_entries),
            )

            if verbose:
                print(f"  Found {len(report.findings)} findings, expected {len(gt_entries)}")
                print(f"  TP={match.tp} FP={match.fp} FN={match.fn}")
                print(f"  P={match.precision:.0%} R={match.recall:.0%} F1={match.f1:.0%}")
                print(f"  Duration: {duration:.1f}s")

                # Show unmatched predictions
                for f in report.findings:
                    matched = False
                    for gt in gt_entries:
                        if (f.location.file_path == gt.file_path
                            and abs(f.location.start_line - gt.start_line) <= LINE_TOLERANCE
                            and (not gt.title_pattern or gt.title_pattern.lower() in f.title.lower())):
                            matched = True
                            break
                    status = "TP" if matched else "FP"
                    print(f"    [{status}] {f.severity.emoji} {f.title} ({f.location.display})")

            results.append(pr)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def print_scorecard(results: list[ProjectResult]) -> None:
    """Print a rich terminal scorecard."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()

        table = Table(title="CodeAudit Benchmark Scorecard", show_lines=True)
        table.add_column("Project", style="bold")
        table.add_column("TP", justify="right")
        table.add_column("FP", justify="right")
        table.add_column("FN", justify="right")
        table.add_column("Precision", justify="right")
        table.add_column("Recall", justify="right")
        table.add_column("F1", justify="right", style="bold")
        table.add_column("Time", justify="right")

        total = MatchResult()
        total_time = 0.0

        for r in results:
            m = r.match
            total.tp += m.tp
            total.fp += m.fp
            total.fn += m.fn
            total_time += r.duration_seconds

            f1_style = "green" if m.f1 >= 0.8 else ("yellow" if m.f1 >= 0.5 else "red")
            table.add_row(
                r.name,
                str(m.tp), str(m.fp), str(m.fn),
                f"{m.precision:.0%}", f"{m.recall:.0%}",
                f"[{f1_style}]{m.f1:.0%}[/{f1_style}]",
                f"{r.duration_seconds:.1f}s",
            )

        # Total row
        f1_style = "green" if total.f1 >= 0.8 else ("yellow" if total.f1 >= 0.5 else "red")
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total.tp}[/bold]", f"[bold]{total.fp}[/bold]", f"[bold]{total.fn}[/bold]",
            f"[bold]{total.precision:.0%}[/bold]",
            f"[bold]{total.recall:.0%}[/bold]",
            f"[bold {f1_style}]{total.f1:.0%}[/bold {f1_style}]",
            f"[bold]{total_time:.1f}s[/bold]",
        )

        console.print()
        console.print(table)
        console.print()

        # Per-dimension breakdown
        dim_table = Table(title="Per-Dimension Breakdown")
        dim_table.add_column("Dimension")
        dim_table.add_column("TP", justify="right")
        dim_table.add_column("FP", justify="right")
        dim_table.add_column("FN", justify="right")
        dim_table.add_column("F1", justify="right", style="bold")
        # (dimension breakdown would require tracking per-dimension matches — placeholder)
        console.print(f"[dim]Per-dimension breakdown requires matched findings tracking (coming soon).[/dim]")

    except ImportError:
        # Fallback plain text
        print("\nCodeAudit Benchmark Scorecard")
        print("-" * 70)
        total = MatchResult()
        for r in results:
            m = r.match
            total.tp += m.tp
            total.fp += m.fp
            total.fn += m.fn
            print(f"  {r.name:<25} TP={m.tp} FP={m.fp} FN={m.fn} "
                  f"P={m.precision:.0%} R={m.recall:.0%} F1={m.f1:.0%} ({r.duration_seconds:.1f}s)")
        print("-" * 70)
        print(f"  {'TOTAL':<25} TP={total.tp} FP={total.fp} FN={total.fn} "
              f"P={total.precision:.0%} R={total.recall:.0%} F1={total.f1:.0%}")


def save_results(results: list[ProjectResult], output_path: Path) -> None:
    """Save benchmark results to JSON."""
    total = MatchResult()
    project_data = []
    for r in results:
        total.tp += r.match.tp
        total.fp += r.match.fp
        total.fn += r.match.fn
        project_data.append({
            "name": r.name,
            "tp": r.match.tp, "fp": r.match.fp, "fn": r.match.fn,
            "precision": round(r.match.precision, 4),
            "recall": round(r.match.recall, 4),
            "f1": round(r.match.f1, 4),
            "finding_count": r.finding_count,
            "expected_count": r.expected_count,
            "duration_seconds": round(r.duration_seconds, 1),
        })

    data = {
        "total": {
            "tp": total.tp, "fp": total.fp, "fn": total.fn,
            "precision": round(total.precision, 4),
            "recall": round(total.recall, 4),
            "f1": round(total.f1, 4),
        },
        "projects": project_data,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Results saved to {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main(verbose: bool = False, output: str | None = None) -> None:
    """Main benchmark entry point."""
    results = await run_benchmark(verbose=verbose)

    if not results:
        print("No results to display.")
        return

    print_scorecard(results)

    output_path = Path(output) if output else SAMPLES_DIR.parent / "results.json"
    save_results(results, output_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run CodeAudit benchmarks")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--output", "-o", default=None)
    args = parser.parse_args()

    asyncio.run(main(verbose=args.verbose, output=args.output))
