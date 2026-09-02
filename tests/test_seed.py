import httpx

from veriforge.environment.seed import SeedActor, SeedResource, SeedSpec, seed_environment
from veriforge.events.bus import EventBus
from veriforge.harness.budget import BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.llm.provider import NullLLMProvider


def make_executor(store):
    registry = ToolRegistry()
    register_builtin_tools(registry, NullLLMProvider())
    bus = EventBus(store)
    budget = BudgetTracker.new("job_1")
    return ToolExecutor(registry, PermissionPolicy(), budget, bus, "job_1")


def test_seed_environment_creates_resources_via_real_api(store, example_app_server):
    spec = SeedSpec(
        actors=[SeedActor(name="owner", role_header="owner"), SeedActor(name="member", role_header="member")],
        resources=[
            SeedResource(creation_path="/projects", actor="owner", count=2),
            SeedResource(creation_path="/projects", actor="member", count=1),
        ],
    )
    executor = make_executor(store)
    try:
        result = seed_environment(example_app_server, spec, executor)
    finally:
        executor.shutdown()

    assert len(result.created) == 3
    assert [r.actor for r in result.created] == ["owner", "owner", "member"]
    assert all("id" in r.body for r in result.created)

    listing = httpx.get(f"{example_app_server}/projects").json()
    assert len(listing["projects"]) == 3


def test_seed_environment_with_no_resources_creates_nothing(store, example_app_server):
    spec = SeedSpec(actors=[], resources=[])
    executor = make_executor(store)
    try:
        result = seed_environment(example_app_server, spec, executor)
    finally:
        executor.shutdown()

    assert result.created == []
