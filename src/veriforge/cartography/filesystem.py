"""Minimal filesystem cartographer.

This is deliberately small: real static analysis (routes, APIs, DB schema,
auth model) is Phase 3 (`repository cartographer`) per docs/PHASES.md. What
lives here is honest, non-hallucinated fact-gathering — file counts, marker
files, extension histogram — that Phase 1's job runner needs to produce a
real ANALYSIS_PENDING step instead of a stub.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".veriforge",
    "dist", "build", ".pytest_cache", ".mypy_cache",
}

MARKER_FILES: dict[str, str] = {
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java-maven",
    "build.gradle": "java-gradle",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
}


def scan_repository(repo_path: str | Path, *, max_files: int = 20_000) -> dict:
    root = Path(repo_path)
    if not root.exists():
        return {"exists": False, "repo_path": str(root)}

    file_count = 0
    ext_counter: Counter[str] = Counter()
    markers_found: list[str] = []
    top_level_dirs: list[str] = []

    for entry in root.iterdir():
        if entry.is_dir() and entry.name not in IGNORED_DIRS:
            top_level_dirs.append(entry.name)

    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            file_count += 1
            if path.name in MARKER_FILES:
                markers_found.append(path.name)
            if path.suffix:
                ext_counter[path.suffix] += 1
            if file_count >= max_files:
                break

    languages = sorted({MARKER_FILES[m] for m in markers_found})

    return {
        "exists": True,
        "repo_path": str(root),
        "file_count": file_count,
        "top_level_dirs": sorted(top_level_dirs),
        "marker_files": sorted(set(markers_found)),
        "detected_languages": languages,
        "top_extensions": ext_counter.most_common(10),
    }
