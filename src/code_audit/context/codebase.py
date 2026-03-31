"""Codebase analysis -- language/framework detection and structure mapping."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from code_audit.config.defaults import EXTENSION_LANGUAGE_MAP, FRAMEWORK_DETECTION


def detect_languages(project_path: Path, changed_files: list[str] | None = None) -> list[str]:
    """Detect programming languages used in the project.

    If changed_files is provided, focuses on those. Otherwise scans the project.
    """
    counter: Counter[str] = Counter()

    if changed_files:
        for f in changed_files:
            ext = Path(f).suffix.lower()
            lang = EXTENSION_LANGUAGE_MAP.get(ext)
            if lang:
                counter[lang] += 1
    else:
        # Scan project for common source files (limited depth)
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                ext = Path(line).suffix.lower()
                lang = EXTENSION_LANGUAGE_MAP.get(ext)
                if lang:
                    counter[lang] += 1
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Return languages sorted by frequency
    return [lang for lang, _ in counter.most_common()]


def detect_frameworks(project_path: Path) -> list[str]:
    """Detect frameworks by checking manifest files for known dependencies."""
    frameworks: list[str] = []

    for manifest_name, checks in FRAMEWORK_DETECTION.items():
        manifest_path = project_path / manifest_name
        if not manifest_path.is_file():
            continue

        try:
            content = manifest_path.read_text(encoding="utf-8").lower()
            for search_str, framework_name in checks:
                if search_str in content and framework_name not in frameworks:
                    frameworks.append(framework_name)
        except (OSError, UnicodeDecodeError):
            continue

    return frameworks


def build_file_tree(project_path: Path, max_depth: int = 3, max_entries: int = 80) -> str:
    """Build a simplified file tree of the project structure.

    Uses git ls-files to respect .gitignore, falls back to directory scan.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        files = [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Fallback: walk directory
        files = []
        for p in project_path.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                try:
                    files.append(str(p.relative_to(project_path)))
                except ValueError:
                    pass

    if not files:
        return "(empty project)"

    # Build tree from file paths, limiting depth
    dirs: set[str] = set()
    shown_files: list[str] = []

    for f in files:
        parts = Path(f).parts
        # Add directory entries up to max_depth
        for i in range(1, min(len(parts), max_depth + 1)):
            dirs.add("/".join(parts[:i]) + ("/" if i < len(parts) else ""))
        # Add file if within depth limit
        if len(parts) <= max_depth + 1:
            shown_files.append(f)

    # Combine and sort
    entries = sorted(dirs | set(shown_files))
    if len(entries) > max_entries:
        entries = entries[:max_entries]
        entries.append(f"... and {len(files) - max_entries} more files")

    return "\n".join(entries)


def analyze_codebase(
    project_path: Path,
    changed_files: list[str] | None = None,
) -> tuple[list[str], list[str], str]:
    """Analyze the codebase and return (languages, frameworks, file_tree).

    This is the main entry point for codebase analysis.
    """
    languages = detect_languages(project_path, changed_files)
    frameworks = detect_frameworks(project_path)
    file_tree = build_file_tree(project_path)
    return languages, frameworks, file_tree
