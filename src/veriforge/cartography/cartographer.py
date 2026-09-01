"""Combines the filesystem scan (file counts/markers) with AST-based Python
analysis (routes, persistence backends) into one repo-facts payload. This is
the Phase 3 "repository cartographer" — still static analysis only, no code
execution, no LLM guessing.

Returns plain JSON-safe dicts (not domain models) — this is a harness tool's
raw observation. `world_model/builder.py` is the one place that turns these
facts into `ApiEndpoint` domain objects, once it knows the project_id.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from veriforge.cartography.filesystem import scan_repository
from veriforge.cartography.python_ast import analyze_repository


def analyze(repo_path: str | Path) -> dict:
    fs_facts = scan_repository(repo_path)
    if not fs_facts.get("exists"):
        return {"filesystem": fs_facts, "endpoints": [], "persistence_backends": [], "in_memory_only": None}

    py_analysis = analyze_repository(repo_path)
    return {
        "filesystem": fs_facts,
        "endpoints": [asdict(e) for e in py_analysis.endpoints],
        "persistence_backends": sorted(py_analysis.persistence_backends),
        "in_memory_only": not py_analysis.persistence_backends,
    }
