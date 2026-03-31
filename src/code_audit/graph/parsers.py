"""Language-specific tree-sitter parsers for extracting symbols and imports.

Each parser knows how to extract functions, classes, imports, and
other symbols from a specific language's AST.
"""

from __future__ import annotations

import re
from pathlib import Path

from tree_sitter import Language, Node, Parser

from code_audit.graph.models import CodeSymbol, Dependency, SymbolKind


def _node_text(node: Node, source: bytes) -> str:
    """Extract the text content of a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_children(node: Node, type_name: str) -> list[Node]:
    """Find all direct children of a specific type."""
    return [c for c in node.children if c.type == type_name]


def _find_first_child(node: Node, type_name: str) -> Node | None:
    """Find the first direct child of a specific type."""
    for c in node.children:
        if c.type == type_name:
            return c
    return None


# ── Python Parser ──────────────────────────────────────────────────


def _get_python_parser() -> Parser:
    import tree_sitter_python as tspython
    parser = Parser(Language(tspython.language()))
    return parser


def parse_python(file_path: str, source: str) -> tuple[list[CodeSymbol], list[Dependency], int]:
    """Parse a Python file and extract symbols and imports."""
    parser = _get_python_parser()
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)

    symbols: list[CodeSymbol] = []
    imports: list[Dependency] = []
    complexity = 0

    def walk(node: Node, parent_class: str | None = None):
        nonlocal complexity

        if node.type == "function_definition":
            name_node = _find_first_child(node, "identifier")
            if name_node:
                name = _node_text(name_node, source_bytes)
                kind = SymbolKind.METHOD if parent_class else SymbolKind.FUNCTION

                # Get decorators
                decorators = []
                if node.prev_named_sibling and node.prev_named_sibling.type == "decorator":
                    decorators.append(_node_text(node.prev_named_sibling, source_bytes))

                # Get signature (first line)
                sig_line = source.split("\n")[node.start_point[0]] if node.start_point[0] < len(source.split("\n")) else ""

                # Get docstring
                docstring = ""
                body = _find_first_child(node, "block")
                if body and body.children:
                    first_stmt = body.children[0] if body.children else None
                    if first_stmt and first_stmt.type == "expression_statement":
                        expr = first_stmt.children[0] if first_stmt.children else None
                        if expr and expr.type == "string":
                            docstring = _node_text(expr, source_bytes).strip("\"'")[:200]

                exported = not name.startswith("_")
                symbols.append(CodeSymbol(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=sig_line.strip(),
                    docstring=docstring,
                    exported=exported,
                    decorators=decorators,
                    parent=parent_class,
                ))

        elif node.type == "class_definition":
            name_node = _find_first_child(node, "identifier")
            if name_node:
                class_name = _node_text(name_node, source_bytes)
                symbols.append(CodeSymbol(
                    name=class_name,
                    kind=SymbolKind.CLASS,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=source.split("\n")[node.start_point[0]].strip(),
                    exported=not class_name.startswith("_"),
                ))
                # Parse methods inside the class
                body = _find_first_child(node, "block")
                if body:
                    for child in body.children:
                        walk(child, parent_class=class_name)
                return  # Don't recurse further (we already handled the body)

        elif node.type == "import_statement":
            text = _node_text(node, source_bytes)
            # import foo, import foo.bar
            match = re.match(r"import\s+([\w.]+)", text)
            if match:
                module = match.group(1)
                imports.append(Dependency(
                    source_file=file_path,
                    target_file=_module_to_path(module),
                    target_symbol=module,
                    kind="import",
                    line=node.start_point[0] + 1,
                ))

        elif node.type == "import_from_statement":
            text = _node_text(node, source_bytes)
            match = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", text)
            if match:
                module = match.group(1)
                imported_names = [n.strip().split(" as ")[0] for n in match.group(2).split(",")]
                for name in imported_names:
                    name = name.strip()
                    if name and name != "(":
                        imports.append(Dependency(
                            source_file=file_path,
                            target_file=_module_to_path(module),
                            target_symbol=name,
                            kind="import",
                            line=node.start_point[0] + 1,
                        ))

        # Count complexity (branching statements)
        elif node.type in ("if_statement", "for_statement", "while_statement",
                           "try_statement", "with_statement", "match_statement"):
            complexity += 1

        # Recurse into children
        for child in node.children:
            walk(child, parent_class)

    walk(tree.root_node)
    return symbols, imports, complexity


# ── TypeScript / JavaScript Parser ─────────────────────────────────


def _get_typescript_parser() -> Parser:
    import tree_sitter_typescript as tstypescript
    parser = Parser(Language(tstypescript.language_typescript()))
    return parser


def _get_tsx_parser() -> Parser:
    import tree_sitter_typescript as tstypescript
    parser = Parser(Language(tstypescript.language_tsx()))
    return parser


def _get_javascript_parser() -> Parser:
    import tree_sitter_javascript as tsjavascript
    parser = Parser(Language(tsjavascript.language()))
    return parser


def parse_typescript(file_path: str, source: str) -> tuple[list[CodeSymbol], list[Dependency], int]:
    """Parse a TypeScript/JavaScript/TSX/JSX file."""
    ext = Path(file_path).suffix.lower()
    if ext == ".tsx" or ext == ".jsx":
        parser = _get_tsx_parser()
    elif ext in (".ts",):
        parser = _get_typescript_parser()
    else:
        parser = _get_javascript_parser()

    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)

    symbols: list[CodeSymbol] = []
    imports: list[Dependency] = []
    complexity = 0

    def walk(node: Node, parent_class: str | None = None, is_exported: bool = False):
        nonlocal complexity

        # Track export statements
        exported = is_exported or node.type in ("export_statement",)

        if node.type in ("function_declaration", "arrow_function", "method_definition"):
            name = ""
            if node.type == "function_declaration":
                name_node = _find_first_child(node, "name")
                if name_node:
                    name = _node_text(name_node, source_bytes)
            elif node.type == "method_definition":
                name_node = _find_first_child(node, "property_identifier")
                if name_node:
                    name = _node_text(name_node, source_bytes)

            if name:
                kind = SymbolKind.METHOD if parent_class else SymbolKind.FUNCTION
                symbols.append(CodeSymbol(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=source.split("\n")[node.start_point[0]].strip()[:120],
                    exported=exported,
                    parent=parent_class,
                ))

        elif node.type == "class_declaration":
            name_node = _find_first_child(node, "type_identifier") or _find_first_child(node, "identifier")
            if name_node:
                class_name = _node_text(name_node, source_bytes)
                symbols.append(CodeSymbol(
                    name=class_name,
                    kind=SymbolKind.CLASS,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=source.split("\n")[node.start_point[0]].strip()[:120],
                    exported=exported,
                ))
                body = _find_first_child(node, "class_body")
                if body:
                    for child in body.children:
                        walk(child, parent_class=class_name, is_exported=exported)
                return

        elif node.type == "interface_declaration":
            name_node = _find_first_child(node, "type_identifier")
            if name_node:
                symbols.append(CodeSymbol(
                    name=_node_text(name_node, source_bytes),
                    kind=SymbolKind.INTERFACE,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    exported=exported,
                ))

        elif node.type == "type_alias_declaration":
            name_node = _find_first_child(node, "type_identifier")
            if name_node:
                symbols.append(CodeSymbol(
                    name=_node_text(name_node, source_bytes),
                    kind=SymbolKind.TYPE_ALIAS,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    exported=exported,
                ))

        elif node.type == "lexical_declaration":
            # const/let/var declarations
            for decl in _find_children(node, "variable_declarator"):
                name_node = _find_first_child(decl, "identifier")
                if name_node:
                    name = _node_text(name_node, source_bytes)
                    # Check if it's a component (PascalCase function/arrow)
                    kind = SymbolKind.VARIABLE
                    if name[0:1].isupper():
                        value = _find_first_child(decl, "arrow_function")
                        if value:
                            kind = SymbolKind.COMPONENT
                    symbols.append(CodeSymbol(
                        name=name,
                        kind=kind,
                        file_path=file_path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        exported=exported,
                    ))

        elif node.type == "import_statement":
            text = _node_text(node, source_bytes)
            # Extract the module path from import ... from "path"
            match = re.search(r"""from\s+['"]([^'"]+)['"]""", text)
            if not match:
                match = re.search(r"""import\s+['"]([^'"]+)['"]""", text)
            if match:
                module_path = match.group(1)
                # Extract imported names
                names_match = re.search(r"import\s*\{([^}]+)\}", text)
                if names_match:
                    for name in names_match.group(1).split(","):
                        name = name.strip().split(" as ")[0].strip()
                        if name:
                            imports.append(Dependency(
                                source_file=file_path,
                                target_file=_resolve_ts_import(file_path, module_path),
                                target_symbol=name,
                                kind="import",
                                line=node.start_point[0] + 1,
                            ))
                else:
                    imports.append(Dependency(
                        source_file=file_path,
                        target_file=_resolve_ts_import(file_path, module_path),
                        kind="import",
                        line=node.start_point[0] + 1,
                    ))

        # Complexity
        elif node.type in ("if_statement", "for_statement", "for_in_statement",
                           "while_statement", "switch_statement", "try_statement",
                           "ternary_expression"):
            complexity += 1

        # Recurse
        for child in node.children:
            walk(child, parent_class, is_exported=exported if node.type == "export_statement" else False)

    walk(tree.root_node)
    return symbols, imports, complexity


# ── Helpers ────────────────────────────────────────────────────────


def _module_to_path(module: str) -> str:
    """Convert a Python module path to a file path guess.

    'code_audit.models.finding' → 'code_audit/models/finding.py'
    """
    parts = module.split(".")
    return "/".join(parts) + ".py"


def _resolve_ts_import(source_file: str, import_path: str) -> str:
    """Resolve a TypeScript/JS import path relative to the source file.

    './utils' → 'src/utils.ts' (relative to source_file)
    '@/components/Button' → 'components/Button.tsx' (alias)
    'react' → 'node_modules/react' (external)
    """
    if import_path.startswith("."):
        # Relative import
        source_dir = str(Path(source_file).parent)
        resolved = str(Path(source_dir) / import_path)
        # Normalize: remove leading ./
        if resolved.startswith("./"):
            resolved = resolved[2:]
        return resolved
    elif import_path.startswith("@/") or import_path.startswith("~/"):
        # Common aliases — strip prefix
        return import_path[2:]
    else:
        # External package
        return f"node_modules/{import_path}"


# ── Language Router ────────────────────────────────────────────────

LANGUAGE_PARSERS = {
    "Python": parse_python,
    "TypeScript": parse_typescript,
    "TypeScript (TSX)": parse_typescript,
    "JavaScript": parse_typescript,  # Same parser handles JS
    "JavaScript (JSX)": parse_typescript,
}


def parse_file(
    file_path: str, source: str, language: str
) -> tuple[list[CodeSymbol], list[Dependency], int]:
    """Parse a file using the appropriate language parser.

    Returns (symbols, imports, complexity_estimate).
    Falls back to empty results for unsupported languages.
    """
    parser_fn = LANGUAGE_PARSERS.get(language)
    if parser_fn is None:
        return [], [], 0

    try:
        return parser_fn(file_path, source)
    except Exception:
        # If parsing fails, return empty results rather than crashing
        return [], [], 0
