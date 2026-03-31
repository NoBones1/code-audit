"""Code graph analyzer — builds a dependency graph from source files.

The analyzer scans changed files and their immediate neighbors to build
a CodeGraph that the review agents can use to understand cross-file
dependencies and impact radius.
"""

from __future__ import annotations

from pathlib import Path

from code_audit.config.defaults import EXTENSION_LANGUAGE_MAP
from code_audit.graph.models import CodeGraph, FileAnalysis
from code_audit.graph.parsers import parse_file


class CodeGraphAnalyzer:
    """Builds a code graph for a project or set of changed files.

    Usage:
        analyzer = CodeGraphAnalyzer(project_path)
        graph = analyzer.analyze(changed_files=["src/auth.py", "src/db.py"])
    """

    def __init__(self, project_path: Path):
        self.project_path = project_path

    def analyze(
        self,
        changed_files: list[str] | None = None,
        include_neighbors: bool = True,
        max_files: int = 100,
    ) -> CodeGraph:
        """Build a code graph, optionally focused on changed files.

        Args:
            changed_files: List of file paths to analyze. If None, scans the whole project.
            include_neighbors: If True, also parse files imported by changed files.
            max_files: Maximum number of files to parse (safety limit).

        Returns:
            A CodeGraph with symbols, dependencies, and impact analysis.
        """
        graph = CodeGraph()
        files_to_parse: list[str] = []

        if changed_files:
            files_to_parse = list(changed_files)
        else:
            # Scan project for parseable files
            files_to_parse = self._discover_files(max_files)

        # Phase 1: Parse all target files
        parsed_count = 0
        for fp in files_to_parse:
            if parsed_count >= max_files:
                break
            analysis = self._parse_single_file(fp)
            if analysis:
                graph.files[fp] = analysis
                graph.dependencies.extend(analysis.imports)
                parsed_count += 1

        # Phase 2: Parse neighbor files (files imported by changed files)
        if include_neighbors and changed_files:
            neighbor_paths: set[str] = set()
            for dep in graph.dependencies:
                target = dep.target_file
                # Skip external packages
                if target.startswith("node_modules/") or "/" not in target:
                    continue
                if target not in graph.files and target not in neighbor_paths:
                    neighbor_paths.add(target)

            for fp in neighbor_paths:
                if parsed_count >= max_files:
                    break
                analysis = self._parse_single_file(fp)
                if analysis:
                    graph.files[fp] = analysis
                    graph.dependencies.extend(analysis.imports)
                    parsed_count += 1

        return graph

    def _parse_single_file(self, file_path: str) -> FileAnalysis | None:
        """Parse a single file and return its analysis."""
        full_path = self.project_path / file_path
        if not full_path.is_file():
            # Try common extensions
            for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
                candidate = self.project_path / (file_path + ext)
                if candidate.is_file():
                    full_path = candidate
                    file_path = file_path + ext
                    break
            else:
                return None

        # Detect language
        ext = full_path.suffix.lower()
        language = EXTENSION_LANGUAGE_MAP.get(ext)
        if not language:
            return None

        # Read file
        try:
            source = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        # Parse
        symbols, imports, complexity = parse_file(file_path, source, language)

        return FileAnalysis(
            file_path=file_path,
            language=language,
            symbols=symbols,
            imports=imports,
            lines_of_code=len(source.split("\n")),
            complexity_estimate=complexity,
        )

    def _discover_files(self, max_files: int) -> list[str]:
        """Discover parseable source files in the project."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            all_files = [f for f in result.stdout.strip().split("\n") if f]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            all_files = []
            for p in self.project_path.rglob("*"):
                if p.is_file() and ".git" not in p.parts:
                    try:
                        all_files.append(str(p.relative_to(self.project_path)))
                    except ValueError:
                        pass

        # Filter to supported languages
        supported_extensions = set(EXTENSION_LANGUAGE_MAP.keys()) & {
            ".py", ".ts", ".tsx", ".js", ".jsx",
        }
        parseable = [
            f for f in all_files
            if Path(f).suffix.lower() in supported_extensions
        ]

        return parseable[:max_files]
