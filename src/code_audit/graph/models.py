"""Data models for the code graph."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    """Types of code symbols we track."""

    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    MODULE = "module"
    INTERFACE = "interface"  # TypeScript
    TYPE_ALIAS = "type_alias"  # TypeScript
    COMPONENT = "component"  # React/Vue
    STRUCT = "struct"  # Go/Rust
    TRAIT = "trait"  # Rust
    ENUM_TYPE = "enum_type"  # Rust
    IMPL = "impl"  # Rust


class CodeSymbol(BaseModel):
    """A named symbol in the codebase (function, class, variable, etc.)."""

    name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    end_line: int
    signature: str = ""  # Function signature or class definition line
    docstring: str = ""
    exported: bool = False  # Whether it's exported / public
    decorators: list[str] = Field(default_factory=list)
    parent: str | None = None  # Parent class/module for methods

    @property
    def qualified_name(self) -> str:
        if self.parent:
            return f"{self.parent}.{self.name}"
        return self.name

    @property
    def display(self) -> str:
        return f"{self.kind.value} {self.qualified_name} ({self.file_path}:{self.start_line})"


class Dependency(BaseModel):
    """A dependency relationship between two symbols or files."""

    source_file: str  # File that imports/references
    target_file: str  # File being imported/referenced
    source_symbol: str = ""  # Symbol doing the importing (if applicable)
    target_symbol: str = ""  # Symbol being imported
    kind: str = "import"  # import | call | inheritance | type_reference
    line: int = 0  # Line in source file where the dependency exists


class FileAnalysis(BaseModel):
    """Analysis result for a single source file."""

    file_path: str
    language: str
    symbols: list[CodeSymbol] = Field(default_factory=list)
    imports: list[Dependency] = Field(default_factory=list)
    lines_of_code: int = 0
    complexity_estimate: int = 0  # Number of branching statements

    @property
    def exported_symbols(self) -> list[CodeSymbol]:
        return [s for s in self.symbols if s.exported]

    @property
    def functions(self) -> list[CodeSymbol]:
        return [s for s in self.symbols if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)]

    @property
    def classes(self) -> list[CodeSymbol]:
        return [s for s in self.symbols if s.kind == SymbolKind.CLASS]


class CodeGraph(BaseModel):
    """The full code graph for a project or set of changed files."""

    files: dict[str, FileAnalysis] = Field(default_factory=dict)
    dependencies: list[Dependency] = Field(default_factory=list)

    @property
    def all_symbols(self) -> list[CodeSymbol]:
        symbols = []
        for fa in self.files.values():
            symbols.extend(fa.symbols)
        return symbols

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_symbols(self) -> int:
        return sum(len(fa.symbols) for fa in self.files.values())

    def get_dependents(self, file_path: str) -> list[str]:
        """Get files that depend on (import from) the given file."""
        return list({
            d.source_file for d in self.dependencies
            if d.target_file == file_path
        })

    def get_dependencies_of(self, file_path: str) -> list[str]:
        """Get files that the given file depends on (imports from)."""
        return list({
            d.target_file for d in self.dependencies
            if d.source_file == file_path
        })

    def get_impact_radius(self, changed_files: list[str], depth: int = 2) -> set[str]:
        """Get the set of files that could be affected by changes to the given files.

        Walks the dependency graph up to `depth` levels of dependents.
        """
        affected: set[str] = set(changed_files)
        frontier = set(changed_files)

        for _ in range(depth):
            next_frontier: set[str] = set()
            for f in frontier:
                for dependent in self.get_dependents(f):
                    if dependent not in affected:
                        next_frontier.add(dependent)
                        affected.add(dependent)
            frontier = next_frontier
            if not frontier:
                break

        return affected

    def _get_dependency_kinds(self, source_file: str, target_file: str) -> list[str]:
        """Get the kinds of dependencies from source to target."""
        return list({
            d.kind for d in self.dependencies
            if d.source_file == source_file and d.target_file == target_file
        })

    def _deps_with_kinds(self, file_path: str) -> list[str]:
        """Get dependencies of a file with their kinds annotated."""
        targets: dict[str, set[str]] = {}
        for d in self.dependencies:
            if d.source_file == file_path:
                targets.setdefault(d.target_file, set()).add(d.kind)
        return [f"{t} ({', '.join(sorted(kinds))})" for t, kinds in list(targets.items())[:10]]

    def _dependents_with_kinds(self, file_path: str) -> list[str]:
        """Get files that depend on this file, with relationship kinds."""
        sources: dict[str, set[str]] = {}
        for d in self.dependencies:
            if d.target_file == file_path:
                sources.setdefault(d.source_file, set()).add(d.kind)
        return [f"{s} ({', '.join(sorted(kinds))})" for s, kinds in list(sources.items())[:10]]

    def _format_symbol(self, s: CodeSymbol) -> str:
        """Format a symbol — use signature if available, else qualified name."""
        if s.signature:
            return s.signature[:80] + ("..." if len(s.signature) > 80 else "")
        return s.qualified_name

    def detect_cycles(self) -> list[list[str]]:
        """Detect circular dependency chains in the file graph."""
        # Build adjacency from dependencies
        adj: dict[str, set[str]] = {}
        for d in self.dependencies:
            adj.setdefault(d.source_file, set()).add(d.target_file)

        cycles: list[list[str]] = []
        visited: set[str] = set()
        path: list[str] = []
        on_stack: set[str] = set()

        def dfs(node: str) -> None:
            if len(cycles) >= 5:
                return  # limit output
            visited.add(node)
            on_stack.add(node)
            path.append(node)
            for neighbor in adj.get(node, set()):
                if neighbor in on_stack:
                    # Found cycle — extract it
                    idx = path.index(neighbor)
                    cycles.append(path[idx:] + [neighbor])
                elif neighbor not in visited:
                    dfs(neighbor)
            path.pop()
            on_stack.discard(node)

        for node in adj:
            if node not in visited:
                dfs(node)
        return cycles

    def format_for_prompt(self, changed_files: list[str] | None = None) -> str:
        """Format the code graph as context for agent prompts."""
        lines: list[str] = []

        if changed_files:
            impact = self.get_impact_radius(changed_files)
            lines.append(f"### Dependency Analysis ({len(impact)} files in impact radius)")
            lines.append("")

            for fp in changed_files:
                if fp not in self.files:
                    continue
                fa = self.files[fp]

                lines.append(f"**{fp}** ({fa.language}, {fa.lines_of_code} LOC, complexity: {fa.complexity_estimate})")

                if fa.symbols:
                    exported = [s for s in fa.symbols if s.exported]
                    internal = [s for s in fa.symbols if not s.exported]
                    if exported:
                        lines.append(f"  Exports: {', '.join(self._format_symbol(s) for s in exported[:10])}")
                    if internal:
                        lines.append(f"  Internal: {', '.join(self._format_symbol(s) for s in internal[:10])}")

                deps = self._deps_with_kinds(fp)
                if deps:
                    lines.append(f"  Imports from: {', '.join(deps)}")

                dependents = self._dependents_with_kinds(fp)
                if dependents:
                    lines.append(f"  Used by: {', '.join(dependents)} (changes here could break these)")

                # 2nd-degree dependents (blast radius)
                direct_deps = self.get_dependents(fp)
                second_degree: set[str] = set()
                for dep in direct_deps:
                    for dd in self.get_dependents(dep):
                        if dd != fp and dd not in direct_deps:
                            second_degree.add(dd)
                if second_degree:
                    lines.append(f"  2nd-degree impact: {', '.join(list(second_degree)[:8])}")

                lines.append("")
        else:
            lines.append(f"### Code Graph ({self.total_files} files, {self.total_symbols} symbols)")

        return "\n".join(lines)

    def format_for_agent(self, dimension: str, changed_files: list[str] | None = None) -> str:
        """Format graph context tailored to a specific agent dimension."""

        if dimension == "security":
            return self._format_for_security(changed_files)
        elif dimension == "performance":
            return self._format_for_performance(changed_files)
        elif dimension == "architectural":
            return self._format_for_architectural(changed_files)
        else:
            return self.format_for_prompt(changed_files)

    def _format_for_security(self, changed_files: list[str] | None) -> str:
        """Security: emphasize exported symbols, high-complexity files (attack surface)."""
        lines: list[str] = [self.format_for_prompt(changed_files)]

        # Highlight high-complexity files (more branches = more attack surface)
        complex_files = sorted(
            [(fp, fa) for fp, fa in self.files.items() if fa.complexity_estimate > 5],
            key=lambda x: x[1].complexity_estimate,
            reverse=True,
        )[:10]
        if complex_files:
            lines.append("\n**High-complexity files (attack surface)**:")
            for fp, fa in complex_files:
                exported = [s for s in fa.symbols if s.exported]
                lines.append(f"  {fp}: complexity {fa.complexity_estimate}, {len(exported)} exported symbols")

        # Show all exported/public entry points across changed files
        if changed_files:
            entry_points: list[str] = []
            for fp in changed_files:
                fa = self.files.get(fp)
                if not fa:
                    continue
                for s in fa.exported_symbols:
                    if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                        entry_points.append(f"  {s.qualified_name} ({fp}:{s.start_line})")
            if entry_points:
                lines.append("\n**Exported entry points (external attack surface)**:")
                lines.extend(entry_points[:15])

        return "\n".join(lines)

    def _format_for_performance(self, changed_files: list[str] | None) -> str:
        """Performance: rank by complexity, flag god objects."""
        lines: list[str] = [self.format_for_prompt(changed_files)]

        # Complexity ranking
        ranked = sorted(
            [(fp, fa) for fp, fa in self.files.items()],
            key=lambda x: x[1].complexity_estimate,
            reverse=True,
        )[:10]
        if ranked and ranked[0][1].complexity_estimate > 0:
            lines.append("\n**Complexity hotspots**:")
            for fp, fa in ranked:
                if fa.complexity_estimate == 0:
                    break
                lines.append(f"  {fp}: complexity {fa.complexity_estimate}, {fa.lines_of_code} LOC")

        # God objects (files with many symbols)
        god_objects = [(fp, fa) for fp, fa in self.files.items() if len(fa.symbols) > 15]
        if god_objects:
            lines.append("\n**Potential god objects (>15 symbols)**:")
            for fp, fa in sorted(god_objects, key=lambda x: len(x[1].symbols), reverse=True)[:5]:
                lines.append(f"  {fp}: {len(fa.symbols)} symbols, {fa.lines_of_code} LOC")

        return "\n".join(lines)

    def _format_for_architectural(self, changed_files: list[str] | None) -> str:
        """Architectural: dependency graph with kinds, circular dependency detection."""
        lines: list[str] = [self.format_for_prompt(changed_files)]

        # Circular dependencies
        cycles = self.detect_cycles()
        if cycles:
            lines.append("\n**Circular dependencies detected**:")
            for cycle in cycles[:5]:
                lines.append(f"  {' → '.join(cycle)}")

        # Full dependency summary with relationship types
        kind_counts: dict[str, int] = {}
        for d in self.dependencies:
            kind_counts[d.kind] = kind_counts.get(d.kind, 0) + 1
        if kind_counts:
            lines.append("\n**Dependency types**:")
            for kind, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {kind}: {count} relationships")

        # Files with most dependents (high coupling)
        dependent_counts: dict[str, int] = {}
        for d in self.dependencies:
            dependent_counts[d.target_file] = dependent_counts.get(d.target_file, 0) + 1
        high_coupling = sorted(dependent_counts.items(), key=lambda x: -x[1])[:5]
        if high_coupling and high_coupling[0][1] > 1:
            lines.append("\n**Most depended-on files (coupling hotspots)**:")
            for fp, count in high_coupling:
                lines.append(f"  {fp}: {count} dependents")

        return "\n".join(lines)
