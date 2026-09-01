from veriforge.domain.enums import FailureCategory, RequirementKind, Verdict
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


def test_is_executable_covers_all_three_phase9_shapes():
    denied_req = Requirement(project_id="p", source_text="x", structured={"expected": "denied"})
    allowed_only_incomplete = Requirement(
        project_id="p", source_text="x", structured={"expected": "allowed_only_for_this_actor"}
    )
    allowed_only_complete = Requirement(
        project_id="p", source_text="x",
        structured={"expected": "allowed_only_for_this_actor", "actor": "owner", "object": "a project"},
    )
    data_invariant_with_endpoint_info = Requirement(
        project_id="p", source_text="x",
        structured={"expected_status": 404, "action": "delete", "object": "project"},
    )
    data_invariant_without_endpoint_info = Requirement(
        project_id="p", source_text="x", structured={"expected_status": 404},
    )
    no_structure_req = Requirement(project_id="p", source_text="x", structured=None)

    assert is_executable(denied_req) is True
    assert is_executable(allowed_only_incomplete) is False  # missing actor/object
    assert is_executable(allowed_only_complete) is True
    assert is_executable(data_invariant_with_endpoint_info) is True
    assert is_executable(data_invariant_without_endpoint_info) is False  # can't resolve an endpoint
    assert is_executable(no_structure_req) is False
    assert is_executable(None) is False


def test_run_experiment_produces_fail_verdict_and_finding_for_the_planted_bug(store, example_app_server):
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=1),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2),
    ]
    requirement = Requirement(
        project_id="p", source_text="Members cannot delete projects.", kind=RequirementKind.NEGATIVE,
        critical=True, structured={"actor": "members", "action": "delete", "object": "projects", "expected": "denied"},
    )
    test = Test(project_id="p", experiment_id="exp_1", name=requirement.source_text)

    result = run_experiment(
        base_url=example_app_server, requirement=requirement, endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test=test,
    )

    assert result.oracle_verdict.verdict == Verdict.FAIL
    assert result.test_run.verdict == Verdict.FAIL
    assert result.test_run.finished_at is not None
    assert result.finding is not None
    # category is UNKNOWN here on purpose -- classifying it is the Phase 7
    # Triager's job (see tests/test_investigation.py), not run_experiment's.
    assert result.finding.category == FailureCategory.UNKNOWN
    assert "VIOLATED" in result.finding.summary
    assert len(result.observations) == 4
    executor.shutdown()


def test_run_experiment_dispatches_to_data_invariant_and_produces_pass(store, example_app_server):
    executor = make_executor(store)
    endpoints = [ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2)]
    requirement = Requirement(
        project_id="p", source_text="Deleting a project that does not exist must return a 404, not a 500.",
        kind=RequirementKind.DATA_INVARIANT, critical=True,
        structured={"expected_status": 404, "forbidden_status": 500, "action": "delete", "object": "project"},
    )
    test = Test(project_id="p", experiment_id="exp_2", name=requirement.source_text)

    result = run_experiment(
        base_url=example_app_server, requirement=requirement, endpoint=endpoints[0],
        all_endpoints=endpoints, tool_executor=executor, test=test,
    )

    assert result.oracle_verdict.verdict == Verdict.PASS  # the app does 404 correctly here
    assert result.finding is None  # no Finding on PASS
    executor.shutdown()


def test_run_experiment_dispatches_to_allowed_only_and_produces_fail(store, example_app_server):
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=1),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2),
    ]
    requirement = Requirement(
        project_id="p", source_text="Only an owner may delete a project.", kind=RequirementKind.AUTHORIZATION,
        critical=True,
        structured={"actor": "owner", "action": "delete", "object": "a project", "expected": "allowed_only_for_this_actor"},
    )
    test = Test(project_id="p", experiment_id="exp_3", name=requirement.source_text)

    result = run_experiment(
        base_url=example_app_server, requirement=requirement, endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test=test,
    )

    assert result.oracle_verdict.verdict == Verdict.FAIL  # not exclusive to "owner"
    assert result.finding is not None
    executor.shutdown()
