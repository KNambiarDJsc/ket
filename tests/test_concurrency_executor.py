from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.events.bus import EventBus
from veriforge.execution.concurrency_executor import execute_duplicate_creation_check
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


# ---- execute_duplicate_creation_check, against the real example-db-app ----

def test_execute_duplicate_creation_check_reveals_no_idempotency_protection(store, example_db_app_server):
    # example-db-app's POST /projects generates a fresh row on every call it
    # actually receives, with no idempotency key -- so a request delivered
    # twice at the network layer (Phase 14's FaultInjectingProxy) genuinely
    # creates two rows, discoverable only by a direct DB read (Phase 11).
    base_url, db_path = example_db_app_server
    executor = make_executor(store)
    endpoint = ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=60)
    requirement = Requirement(
        project_id="p",
        source_text="A duplicated project-creation request must not create two projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
        structured={"concurrency_check": "no_duplicate_on_creation_replay", "object": "projects", "action": "create"},
    )

    result = execute_duplicate_creation_check(
        base_url=base_url, db_path=db_path, requirement=requirement, action_endpoint=endpoint,
        tool_executor=executor, test_run_id="run_1",
    )

    assert result.row_count_delta == 2  # the real, undesirable outcome
    assert [o.tool for o in result.observations] == ["database.query_sqlite", "api.post", "database.query_sqlite"]
    assert "deliver this request to the backend twice" in result.observations[1].action
    executor.shutdown()


def test_execute_duplicate_creation_check_counts_from_a_nonzero_baseline(store, example_db_app_server):
    # The check must measure a *delta*, not an absolute count -- confirming
    # it still reports exactly 2 new rows when the table already had data.
    base_url, db_path = example_db_app_server
    executor = make_executor(store)
    endpoint = ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=60)
    requirement = Requirement(
        project_id="p",
        source_text="A duplicated project-creation request must not create two projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
        structured={"concurrency_check": "no_duplicate_on_creation_replay", "object": "projects", "action": "create"},
    )

    executor.call("api.post", url=base_url + "/projects")  # unrelated pre-existing row

    result = execute_duplicate_creation_check(
        base_url=base_url, db_path=db_path, requirement=requirement, action_endpoint=endpoint,
        tool_executor=executor, test_run_id="run_1",
    )

    assert result.row_count_delta == 2
    executor.shutdown()
