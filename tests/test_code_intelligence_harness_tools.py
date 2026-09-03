"""Phase 18: confirms code.search/code.read_symbol/code.find_callers are
registered and actually reachable through the full harness stack (registry
-> permissions -> budget -> executor), not just callable as bare functions.
"""
from pathlib import Path

from veriforge.events.bus import EventBus
from veriforge.harness.budget import BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.llm.provider import LLMProvider

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src" / "veriforge")


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


def test_code_search_reachable_through_the_harness(store):
    executor = make_executor(store)
    matches = executor.call("code.search", repo_path=REPO_SRC, query="no idempotency")
    assert len(matches) >= 2
    executor.shutdown()


def test_code_read_symbol_reachable_through_the_harness(store):
    executor = make_executor(store)
    source = executor.call("code.read_symbol", repo_path=REPO_SRC, name="find_creation_endpoint")
    assert source is not None
    assert "def find_creation_endpoint(" in source
    executor.shutdown()


def test_code_find_callers_reachable_through_the_harness(store):
    executor = make_executor(store)
    callers = executor.call("code.find_callers", repo_path=REPO_SRC, name="find_creation_endpoint")
    assert len(callers) >= 4
    executor.shutdown()
