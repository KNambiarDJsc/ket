"""AST-based static analysis of Python sources.

Deliberately not LLM-based: every fact here comes from parsing real source
with the `ast` module, so it can't hallucinate an endpoint that doesn't
exist. Coverage is heuristic (Flask/FastAPI-style decorators, Django-style
`path()` calls, and stdlib `http.server`-style `do_<METHOD>` handlers) —
extend the pattern list as new frameworks show up in real target repos
rather than trying to handle every framework up front.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from veriforge.cartography.filesystem import IGNORED_DIRS

HTTP_METHOD_DECORATORS = {"get", "post", "put", "delete", "patch", "options", "head"}
DO_METHOD_PREFIX = "do_"
ROLE_HINTS = ("role", "permission", "authoriz", "authenticat", "x-role", "is_admin", "session")

PERSISTENCE_IMPORT_MARKERS = {
    "sqlite3": "sqlite",
    "sqlalchemy": "sqlalchemy",
    "psycopg2": "postgres",
    "asyncpg": "postgres",
    "pymongo": "mongodb",
    "motor": "mongodb",
    "redis": "redis",
    "django.db": "django-orm",
}


@dataclass
class DiscoveredEndpoint:
    method: str
    path: str
    source_file: str
    source_line: int
    mentions_role_check: bool = False


@dataclass
class PythonAnalysis:
    endpoints: list[DiscoveredEndpoint] = field(default_factory=list)
    persistence_backends: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    parse_errors: list[str] = field(default_factory=list)


def _decorator_call_name(decorator: ast.expr) -> tuple[str | None, str | None]:
    """Returns (attribute_name, receiver_name) for `@app.get(...)` -> ("get", "app")."""
    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
        attr = decorator.func.attr
        receiver = decorator.func.value.id if isinstance(decorator.func.value, ast.Name) else None
        return attr, receiver
    return None, None


def _first_string_arg(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _methods_kwarg(call: ast.Call) -> list[str]:
    for kw in call.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            return [
                elt.value.upper()
                for elt in kw.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return []


def _mentions_role_hint(node: ast.AST) -> bool:
    source = ast.dump(node)
    lower = source.lower()
    return any(hint in lower for hint in ROLE_HINTS)


def _extract_do_method_endpoints(func: ast.FunctionDef, filename: str) -> list[DiscoveredEndpoint]:
    """stdlib http.server style: a `do_GET`/`do_POST`/... method whose body
    compares `self.path` (or calls `.startswith`) against string literals."""
    method = func.name[len(DO_METHOD_PREFIX):].upper()
    role_hint = _mentions_role_hint(func)
    found: list[DiscoveredEndpoint] = []

    for node in ast.walk(func):
        # self.path == "/literal"  or  "/literal" == self.path
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            operands = [node.left, node.comparators[0]]
            literal = next((o.value for o in operands if isinstance(o, ast.Constant) and isinstance(o.value, str)), None)
            is_self_path = any(
                isinstance(o, ast.Attribute) and o.attr == "path" and isinstance(o.value, ast.Name) and o.value.id == "self"
                for o in operands
            )
            if literal is not None and is_self_path:
                found.append(DiscoveredEndpoint(method, literal, filename, func.lineno, role_hint))

        # self.path.startswith("/literal/")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
        ):
            literal = _first_string_arg(node)
            if literal is not None:
                found.append(DiscoveredEndpoint(method, literal, filename, func.lineno, role_hint))

    return found


def analyze_file(path: Path, repo_root: Path) -> tuple[list[DiscoveredEndpoint], set[str]]:
    rel = str(path.relative_to(repo_root))
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError):
        return [], set()

    endpoints: list[DiscoveredEndpoint] = []
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

        if isinstance(node, ast.FunctionDef):
            # Flask/FastAPI-style: @app.get("/x"), @router.post("/x", ...), @app.route("/x", methods=[...])
            for decorator in node.decorator_list:
                attr, _receiver = _decorator_call_name(decorator)
                if attr is None or not isinstance(decorator, ast.Call):
                    continue
                path_literal = _first_string_arg(decorator)
                if path_literal is None:
                    continue
                if attr in HTTP_METHOD_DECORATORS:
                    endpoints.append(
                        DiscoveredEndpoint(attr.upper(), path_literal, rel, node.lineno, _mentions_role_hint(node))
                    )
                elif attr == "route":
                    methods = _methods_kwarg(decorator) or ["GET"]
                    for m in methods:
                        endpoints.append(
                            DiscoveredEndpoint(m, path_literal, rel, node.lineno, _mentions_role_hint(node))
                        )

            # stdlib http.server style
            if node.name.startswith(DO_METHOD_PREFIX) and node.name[len(DO_METHOD_PREFIX):].isalpha():
                endpoints.extend(_extract_do_method_endpoints(node, rel))

        # Django-style: path("x/", view) / re_path("x/", view) at module level in urls.py
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("path", "re_path"):
            path_literal = _first_string_arg(node)
            if path_literal is not None:
                endpoints.append(DiscoveredEndpoint("ANY", path_literal, rel, node.lineno, False))

    return endpoints, imports


def analyze_repository(repo_path: str | Path) -> PythonAnalysis:
    root = Path(repo_path)
    result = PythonAnalysis()
    if not root.exists():
        return result

    for py_file in root.rglob("*.py"):
        if any(part in IGNORED_DIRS for part in py_file.parts):
            continue
        endpoints, imports = analyze_file(py_file, root)
        result.endpoints.extend(endpoints)
        result.imports.update(imports)

    for module_name in result.imports:
        for marker, backend in PERSISTENCE_IMPORT_MARKERS.items():
            if module_name == marker or module_name.startswith(marker + "."):
                result.persistence_backends.add(backend)

    return result
