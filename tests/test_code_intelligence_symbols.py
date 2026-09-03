"""Phase 18: verified against this project's own `src/veriforge/` tree, not
a toy fixture -- the phase's own reasoning for existing is that code
intelligence only earns its complexity against a real, multi-file
codebase.
"""
from pathlib import Path

from veriforge.code_intelligence.symbols import build_symbol_index, find_callers, read_symbol, search_code

REPO_SRC = Path(__file__).resolve().parents[1] / "src" / "veriforge"


def test_build_symbol_index_finds_real_functions_and_classes():
    index = build_symbol_index(REPO_SRC)

    names = {s.qualname for s in index.symbols}
    assert "find_creation_endpoint" in names
    assert "ToolExecutor" in names
    assert "ToolExecutor.call" in names  # a real method, qualified by its class


def test_read_symbol_returns_real_source_for_a_known_function():
    index = build_symbol_index(REPO_SRC)

    source = read_symbol(index, "find_creation_endpoint")

    assert source is not None
    assert "def find_creation_endpoint(" in source
    assert "POST endpoint" in source  # from the function's own real docstring


def test_read_symbol_returns_none_for_an_unknown_name():
    index = build_symbol_index(REPO_SRC)
    assert read_symbol(index, "this_function_does_not_exist_anywhere") is None


def test_find_callers_finds_real_cross_file_call_sites():
    index = build_symbol_index(REPO_SRC)

    callers = find_callers(index, "find_creation_endpoint")

    files = {c.file for c in callers}
    assert len(callers) >= 4  # http_executor.py (x3) + db_executor.py, at minimum
    assert any("http_executor.py" in f for f in files)
    assert any("db_executor.py" in f for f in files)
    assert all(c.caller_qualname for c in callers)  # every real call site is inside a named function


def test_find_callers_returns_empty_for_an_uncalled_name():
    index = build_symbol_index(REPO_SRC)
    assert find_callers(index, "this_function_is_never_called_anywhere") == []


def test_search_code_finds_real_planted_content():
    matches = search_code(REPO_SRC, "no idempotency", max_results=10)

    assert len(matches) >= 2
    assert any("oracle.py" in m.file for m in matches)
    assert all("no idempotency" in m.line.lower() for m in matches)


def test_search_code_respects_max_results():
    matches = search_code(REPO_SRC, "def ", max_results=5)  # matches almost every file
    assert len(matches) <= 5


def test_search_code_against_a_missing_repo_returns_empty():
    assert search_code("/this/path/does/not/exist", "anything") == []
