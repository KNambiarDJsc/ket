import sqlite3

import pytest

from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.events.bus import EventBus
from veriforge.execution.db_executor import execute_db_removal_check, run_read_only_query
from veriforge.harness.budget import BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.llm.provider import LLMProvider


class NullLLM(LLMProvider):
    def generate(self, prompt, *, system=None):
        return ""

    def is_available(self):
        return False

    @property
    def model_name(self):
        return "null"


def make_executor(store):
    registry = ToolRegistry()
    register_builtin_tools(registry, NullLLM())
    bus = EventBus(store)
    budget = BudgetTracker.new("job_1")
    return ToolExecutor(registry, PermissionPolicy(), budget, bus, "job_1")


# ---- run_read_only_query ----

def test_run_read_only_query_returns_rows(tmp_path):
    db_path = str(tmp_path / "t.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE widgets (id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO widgets VALUES ('w1', 'Widget One')")
    conn.commit()
    conn.close()

    rows = run_read_only_query(db_path, "SELECT id, name FROM widgets WHERE id = ?", ["w1"])
    assert rows == [{"id": "w1", "name": "Widget One"}]


def test_run_read_only_query_rejects_non_select(tmp_path):
    db_path = str(tmp_path / "t.db")
    sqlite3.connect(db_path).close()
    with pytest.raises(ValueError, match="read-only SELECT"):
        run_read_only_query(db_path, "DELETE FROM widgets")


def test_run_read_only_query_rejects_non_select_case_insensitively(tmp_path):
    db_path = str(tmp_path / "t.db")
    sqlite3.connect(db_path).close()
    with pytest.raises(ValueError, match="read-only SELECT"):
        run_read_only_query(db_path, "  drop table widgets; ")


# ---- execute_db_removal_check, against the real example-db-app ----

def test_execute_db_removal_check_reveals_the_planted_soft_delete_bug(store, example_db_app_server):
    base_url, db_path = example_db_app_server
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=60),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=75),
    ]
    requirement = Requirement(
        project_id="p",
        source_text="Deleted projects must be permanently removed from the database, not merely hidden.",
        kind=RequirementKind.FUNCTIONAL, critical=True,
        structured={"db_check": "removed_after_delete", "object": "projects", "action": "delete"},
    )

    result = execute_db_removal_check(
        base_url=base_url, db_path=db_path, requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test_run_id="run_1",
    )

    assert result.api_delete_status == 200  # the API claims success
    assert result.row_still_in_db is True  # but the row is only soft-deleted
    assert [o.tool for o in result.observations] == ["api.post", "api.delete", "database.query_sqlite"]
    assert "bypassing the API" in result.observations[-1].action
    executor.shutdown()
