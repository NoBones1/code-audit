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

    def format_for_prompt(self, changed_files: list[str] | None = None) -> str:
        """Format the code graph as context for agent prompts."""
        lines: list[str] = []

        # If we have changed files, focus on their neighborhood
        if changed_files:
            impact = self.get_impact_radius(changed_files)
            lines.append(f"### Dependency Analysis ({len(impact)} files in impact radius)")
            lines.append("")

            for fp in changed_files:
                if fp not in self.files:
                    continue
                fa = self.files[fp]

                lines.append(f"**{fp}** ({fa.language}, {fa.lines_of_code} LOC)")

                # Symbols defined here
                if fa.symbols:
                    exported = [s for s in fa.symbols if s.exported]
                    internal = [s for s in fa.symbols if not s.exported]
                    if exported:
                        lines.append(f"  Exports: {', '.join(s.qualified_name for s in exported[:10])}")
                    if internal:
                        lines.append(f"  Internal: {', '.join(s.qualified_name for s in internal[:10])}")

                # What this file imports
                deps = self.get_dependencies_of(fp)
                if deps:
                    lines.append(f"  Imports from: {', '.join(deps[:10])}")

                # What files depend on this file (could break if we change exports)
                dependents = self.get_dependents(fp)
                if dependents:
                    lines.append(f"  Used by: {', '.join(dependents[:10])} (changes here could break these)")

                lines.append("")
        else:
            lines.append(f"### Code Graph ({self.total_files} files, {self.total_symbols} symbols)")

        return "\n".join(lines)
