from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.events.bus import EventBus
from veriforge.execution.http_executor import (
    execute_allowed_only_for_actor_check,
    execute_authorization_check,
    execute_data_invariant_check,
    find_creation_endpoint,
    origin_of,
)
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


def test_find_creation_endpoint_matches_post_by_object_keyword():
    endpoints = [
        ApiEndpoint(project_id="p", method="GET", path="/projects", source_file="a.py", source_line=1),
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="a.py", source_line=2),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="a.py", source_line=3),
    ]
    result = find_creation_endpoint("projects", endpoints)
    assert result.method == "POST"


def test_find_creation_endpoint_returns_none_when_no_object_keyword():
    assert find_creation_endpoint("", []) is None


def test_origin_of_strips_path_and_query():
    assert origin_of("http://localhost:8000/ui") == "http://localhost:8000"
    assert origin_of("http://localhost:8000/ui?tab=projects") == "http://localhost:8000"
    assert origin_of("http://localhost:8000") == "http://localhost:8000"


def test_execute_authorization_check_uses_origin_not_the_full_url_with_path(store, example_app_server):
    # Regression test: job.base_url may be a UI entry point like f"{origin}/ui"
    # (that's what the browser explorer needs) -- the Executor must call the
    # API at the origin, not at f"{origin}/ui/projects". This broke a real
    # CLI run (UNCERTAIN/404 instead of the correct FAIL) before origin_of()
    # was introduced.
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=1),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2),
    ]
    requirement = Requirement(
        project_id="p", source_text="Members cannot delete projects.", kind=RequirementKind.NEGATIVE,
        critical=True, structured={"actor": "members", "action": "delete", "object": "projects", "expected": "denied"},
    )

    result = execute_authorization_check(
        base_url=f"{example_app_server}/ui", requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test_run_id="run_1",
    )

    assert result.response_status == 200  # not 404 -- it actually hit /projects/<id>
    assert result.resource_still_present is False
    executor.shutdown()


def test_execute_authorization_check_against_real_example_app(store, example_app_server):
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="GET", path="/projects", source_file="app.py", source_line=1, mentions_role_check=False),
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=2, mentions_role_check=False),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=3, mentions_role_check=False),
    ]
    requirement = Requirement(
        project_id="p", source_text="Members cannot delete projects.", kind=RequirementKind.NEGATIVE,
        critical=True, structured={"actor": "members", "action": "delete", "object": "projects", "expected": "denied"},
    )
    delete_endpoint = endpoints[2]

    result = execute_authorization_check(
        base_url=example_app_server, requirement=requirement, action_endpoint=delete_endpoint,
        all_endpoints=endpoints, tool_executor=executor, test_run_id="run_1",
    )

    assert result.response_status == 200  # the app wrongly allows it
    assert result.resource_still_present is False  # and it's actually gone
    tools = [o.tool for o in result.observations]
    assert tools == ["api.post", "api.get", "api.delete", "api.get"]
    assert result.observations[2].action.endswith("as role='member'")
    executor.shutdown()


def test_execute_data_invariant_check_against_real_example_app(store, example_app_server):
    executor = make_executor(store)
    delete_endpoint = ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=46)

    result = execute_data_invariant_check(
        base_url=example_app_server, action_endpoint=delete_endpoint,
        tool_executor=executor, test_run_id="run_1",
    )

    assert result.response_status == 404  # the app correctly 404s a nonexistent project
    assert len(result.observations) == 1
    assert "nonexistent-00000000" in result.observations[0].action
    executor.shutdown()


def test_execute_allowed_only_for_actor_check_reveals_no_exclusivity(store, example_app_server):
    # The example app never checks role at all, so a "not-owner" can delete
    # just as easily as an "owner" -- this should surface as a real second
    # bug via the same mechanism as the "denied" case.
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=38),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=46),
    ]
    requirement = Requirement(
        project_id="p", source_text="Only an owner may delete a project.", kind=RequirementKind.AUTHORIZATION,
        critical=True, structured={"actor": "owner", "action": "delete", "object": "a project", "expected": "allowed_only_for_this_actor"},
    )

    result = execute_allowed_only_for_actor_check(
        base_url=example_app_server, requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test_run_id="run_1",
    )

    assert result.actor_status == 200 and result.actor_resource_gone is True
    assert result.other_status == 200 and result.other_resource_gone is True  # not actually exclusive
    assert len(result.observations) == 6  # 2x (create, action, state-check)
    actor_action = next(o for o in result.observations if "role='owner'" in o.action and o.tool == "api.delete")
    other_action = next(o for o in result.observations if "role='not-owner'" in o.action and o.tool == "api.delete")
    assert actor_action is not None and other_action is not None
    executor.shutdown()
