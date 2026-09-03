"""Code Intelligence (Phase 18): `search_code`/`read_symbol`/`find_callers`
-- real, AST-based tools for answering "where is this defined" and "who
calls this" directly, instead of a human (or an LLM) re-reading files by
hand. Deliberately not built earlier: this only earns its complexity
against a real multi-file codebase, not a 70-line example app -- every
prior phase's fixtures were exactly that, so this phase's own tests point
it at this project's own `src/veriforge/` tree instead.

Reuses `cartography.python_ast`'s exact walking pattern (same `IGNORED_DIRS`,
same `ast.parse`-and-skip-on-syntax-error shape) rather than duplicating
it, but for a different fact: general function/class symbols and call
sites, not HTTP routes.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from veriforge.cartography.filesystem import IGNORED_DIRS


@dataclass
class Symbol:
    name: str
    qualname: str  # "ToolExecutor.call" for a method, "run_experiment" for a module-level function
    kind: str  # "function" | "async function" | "class" | "method" | "async method"
    file: str  # repo-relative path
    lineno: int
    end_lineno: int


@dataclass
class CallSite:
    called_name: str  # the raw name being called -- "call", "run_experiment", etc.
    caller_qualname: str  # enclosing function/method, "" for module-level code
    file: str
    lineno: int


@dataclass
class SymbolIndex:
    symbols: list[Symbol] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)
    _source_by_file: dict[str, list[str]] = field(default_factory=dict, repr=False)


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _walk_functions(
    body: list[ast.stmt], file_rel: str, index: SymbolIndex, *, class_name: str | None = None
) -> None:
    for node in body:
        if isinstance(node, ast.ClassDef):
            qualname = node.name
            index.symbols.append(Symbol(node.name, qualname, "class", file_rel, node.lineno, node.end_lineno or node.lineno))
            _walk_functions(node.body, file_rel, index, class_name=node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_method = class_name is not None
            qualname = f"{class_name}.{node.name}" if is_method else node.name
            kind_base = "method" if is_method else "function"
            kind = f"async {kind_base}" if isinstance(node, ast.AsyncFunctionDef) else kind_base
            index.symbols.append(Symbol(node.name, qualname, kind, file_rel, node.lineno, node.end_lineno or node.lineno))
            for call_node in ast.walk(node):
                if isinstance(call_node, ast.Call):
                    called = _call_name(call_node)
                    if called:
                        index.call_sites.append(CallSite(called, qualname, file_rel, call_node.lineno))
            # nested functions/classes defined inside this one
            _walk_functions(node.body, file_rel, index, class_name=class_name)


def build_symbol_index(repo_path: str | Path) -> SymbolIndex:
    root = Path(repo_path)
    index = SymbolIndex()
    if not root.exists():
        return index

    for py_file in root.rglob("*.py"):
        if any(part in IGNORED_DIRS for part in py_file.parts):
            continue
        rel = str(py_file.relative_to(root))
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        index._source_by_file[rel] = source.splitlines()

        _walk_functions(tree.body, rel, index)
        # module-level calls (caller_qualname="") -- e.g. register_builtin_tools(...)
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                called = _call_name(node.value)
                if called:
                    index.call_sites.append(CallSite(called, "", rel, node.value.lineno))

    return index


def read_symbol(index: SymbolIndex, name: str) -> str | None:
    """Returns the source text of the first symbol whose bare name or
    qualname matches -- `name` (a method name alone, ambiguous across
    classes) or `Class.method` (unambiguous)."""
    match = next((s for s in index.symbols if s.qualname == name or s.name == name), None)
    if match is None:
        return None
    lines = index._source_by_file.get(match.file, [])
    return "\n".join(lines[match.lineno - 1:match.end_lineno])


def find_callers(index: SymbolIndex, name: str) -> list[CallSite]:
    return [c for c in index.call_sites if c.called_name == name]


@dataclass
class CodeMatch:
    file: str
    lineno: int
    line: str


def search_code(repo_path: str | Path, query: str, *, max_results: int = 50) -> list[CodeMatch]:
    """Grep-style, case-insensitive substring search across every `.py`
    file -- the lexical leg of retrieval, deliberately not AST-aware (a
    literal string, a comment, a docstring are all fair matches for
    "where does this project mention X")."""
    root = Path(repo_path)
    matches: list[CodeMatch] = []
    if not root.exists():
        return matches
    needle = query.lower()

    for py_file in sorted(root.rglob("*.py")):
        if any(part in IGNORED_DIRS for part in py_file.parts):
            continue
        rel = str(py_file.relative_to(root))
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(lines, start=1):
            if needle in line.lower():
                matches.append(CodeMatch(rel, i, line.strip()))
                if len(matches) >= max_results:
                    return matches
    return matches
