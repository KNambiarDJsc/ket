import pytest

from veriforge.domain.enums import RequirementKind, Verdict
from veriforge.domain.models import ApiEndpoint, Requirement, Test
from veriforge.events.bus import EventBus
from veriforge.execution.experiment_runner import is_executable, run_experiment
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


# ---- is_executable ----

def test_endpoint_exposed_is_executable_with_method_and_path():
    req = Requirement(
        project_id="p", source_text="x", kind=RequirementKind.FUNCTIONAL,
        structured={"contract": "endpoint_exposed", "label": "health check", "method": "GET", "path": "/"},
    )
    assert is_executable(req) is True


def test_creation_visible_is_executable_with_object_method_and_path():
    req = Requirement(
        project_id="p", source_text="x", kind=RequirementKind.ORDERING,
        structured={"contract": "creation_visible_in_listing", "object": "project", "method": "GET", "path": "/projects"},
    )
    assert is_executable(req) is True


def test_unknown_contract_shape_is_not_executable():
    req = Requirement(
        project_id="p", source_text="x", kind=RequirementKind.ORDERING,
        structured={"contract": "some_future_kind"},
    )
    assert is_executable(req) is False


def test_db_removal_is_executable_with_action_and_object():
    req = Requirement(
        project_id="p", source_text="x", kind=RequirementKind.FUNCTIONAL,
        structured={"db_check": "removed_after_delete", "object": "projects", "action": "delete"},
    )
    assert is_executable(req) is True


def test_duplicate_creation_is_executable_with_action_and_object():
    req = Requirement(
        project_id="p", source_text="x", kind=RequirementKind.NEGATIVE,
        structured={"concurrency_check": "no_duplicate_on_creation_replay", "object": "projects", "action": "create"},
    )
    assert is_executable(req) is True


# ---- run_experiment dispatch, against the real example app ----

def test_run_experiment_endpoint_exposed_passes_against_real_app(store, example_app_server):
    executor = make_executor(store)
    requirement = Requirement(
        project_id="p", source_text="The service must expose a health check at GET /.",
        kind=RequirementKind.FUNCTIONAL, critical=True,
        structured={"contract": "endpoint_exposed", "label": "health check", "method": "GET", "path": "/"},
    )
    endpoint = ApiEndpoint(project_id="p", method="GET", path="/", source_file="app.py", source_line=80)
    test = Test(project_id="p", name=requirement.source_text)

    result = run_experiment(
        base_url=example_app_server, requirement=requirement, endpoint=endpoint,
        all_endpoints=[endpoint], tool_executor=executor, test=test,
    )

    assert result.test_run.verdict == Verdict.PASS
    assert result.oracle_verdict.verdict == Verdict.PASS
    assert result.finding is None  # only FAIL verdicts produce a Finding
    executor.shutdown()


def test_run_experiment_creation_visible_passes_against_real_app(store, example_app_server):
    executor = make_executor(store)
    requirement = Requirement(
        project_id="p",
        source_text="A newly created project must appear in GET /projects immediately after creation.",
        kind=RequirementKind.ORDERING, critical=True,
        structured={"contract": "creation_visible_in_listing", "object": "project", "method": "GET", "path": "/projects"},
    )
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=38),
        ApiEndpoint(project_id="p", method="GET", path="/projects", source_file="app.py", source_line=30),
    ]
    test = Test(project_id="p", name=requirement.source_text)

    result = run_experiment(
        base_url=example_app_server, requirement=requirement, endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test=test,
    )

    assert result.oracle_verdict.verdict == Verdict.PASS
    assert result.finding is None
    assert [o.tool for o in result.observations] == ["api.post", "api.get"]
    executor.shutdown()


def test_run_experiment_db_removal_without_db_path_raises(store, example_db_app_server):
    base_url, _db_path = example_db_app_server
    executor = make_executor(store)
    requirement = Requirement(
        project_id="p",
        source_text="Deleted projects must be permanently removed from the database, not merely hidden.",
        kind=RequirementKind.FUNCTIONAL, critical=True,
        structured={"db_check": "removed_after_delete", "object": "projects", "action": "delete"},
    )
    endpoint = ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=75)
    test = Test(project_id="p", name=requirement.source_text)

    with pytest.raises(ValueError, match="db_path"):
        run_experiment(
            base_url=base_url, requirement=requirement, endpoint=endpoint,
            all_endpoints=[endpoint], tool_executor=executor, test=test,
        )
    executor.shutdown()


def test_run_experiment_db_removal_fails_against_real_app_when_db_path_given(store, example_db_app_server):
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
    test = Test(project_id="p", name=requirement.source_text)

    result = run_experiment(
        base_url=base_url, requirement=requirement, endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test=test, db_path=db_path,
    )

    assert result.oracle_verdict.verdict == Verdict.FAIL  # the planted soft-delete bug
    assert result.finding is not None
    executor.shutdown()


def test_run_experiment_duplicate_creation_without_db_path_raises(store, example_db_app_server):
    base_url, _db_path = example_db_app_server
    executor = make_executor(store)
    requirement = Requirement(
        project_id="p",
        source_text="A duplicated project-creation request must not create two projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
        structured={"concurrency_check": "no_duplicate_on_creation_replay", "object": "projects", "action": "create"},
    )
    endpoint = ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=60)
    test = Test(project_id="p", name=requirement.source_text)

    with pytest.raises(ValueError, match="db_path"):
        run_experiment(
            base_url=base_url, requirement=requirement, endpoint=endpoint,
            all_endpoints=[endpoint], tool_executor=executor, test=test,
        )
    executor.shutdown()


def test_run_experiment_duplicate_creation_fails_against_real_app_when_db_path_given(store, example_db_app_server):
    # example-db-app has no idempotency protection at all -- a request
    # delivered twice at the network layer genuinely creates two rows.
    base_url, db_path = example_db_app_server
    executor = make_executor(store)
    requirement = Requirement(
        project_id="p",
        source_text="A duplicated project-creation request must not create two projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
        structured={"concurrency_check": "no_duplicate_on_creation_replay", "object": "projects", "action": "create"},
    )
    endpoint = ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=60)
    test = Test(project_id="p", name=requirement.source_text)

    result = run_experiment(
        base_url=base_url, requirement=requirement, endpoint=endpoint,
        all_endpoints=[endpoint], tool_executor=executor, test=test, db_path=db_path,
    )

    assert result.oracle_verdict.verdict == Verdict.FAIL
    assert result.finding is not None
    assert [o.tool for o in result.observations] == ["database.query_sqlite", "api.post", "database.query_sqlite"]
    executor.shutdown()
