import time

import pytest

from veriforge.domain.enums import RiskLevel
from veriforge.events.bus import EventBus
from veriforge.harness.budget import BudgetExceededError, BudgetTracker
from veriforge.harness.executor import ToolExecutor, ToolTimeoutError
from veriforge.harness.permissions import PermissionDeniedError, PermissionPolicy
from veriforge.harness.tools import RetryPolicy, ToolRegistry, ToolSpec


def make_executor(store, *, policy=None, max_tool_calls=None):
    registry = ToolRegistry()
    bus = EventBus(store)
    budget = BudgetTracker.new("job_1", max_tool_calls=max_tool_calls)
    executor = ToolExecutor(registry, policy or PermissionPolicy(), budget, bus, "job_1")
    return registry, bus, budget, executor


def test_successful_call_publishes_started_and_succeeded(store):
    registry, bus, budget, executor = make_executor(store)
    registry.register(
        ToolSpec(name="echo", description="d", risk=RiskLevel.READ), handler=lambda x: x * 2
    )

    result = executor.call("echo", x=21)

    assert result == 42
    event_types = [e.type.value for e in bus.history("job_1")]
    assert "TOOL_CALL_STARTED" in event_types
    assert "TOOL_CALL_SUCCEEDED" in event_types
    executor.shutdown()


def test_destructive_tool_denied(store):
    registry, bus, budget, executor = make_executor(store)
    registry.register(
        ToolSpec(name="danger", description="d", risk=RiskLevel.DESTRUCTIVE), handler=lambda: None
    )

    with pytest.raises(PermissionDeniedError):
        executor.call("danger")

    event_types = [e.type.value for e in bus.history("job_1")]
    assert "TOOL_CALL_DENIED" in event_types
    executor.shutdown()


def test_budget_exceeded_blocks_call(store):
    registry, bus, budget, executor = make_executor(store, max_tool_calls=1)
    registry.register(ToolSpec(name="noop", description="d", risk=RiskLevel.READ), handler=lambda: None)

    executor.call("noop")
    with pytest.raises(BudgetExceededError):
        executor.call("noop")

    event_types = [e.type.value for e in bus.history("job_1")]
    assert "BUDGET_EXCEEDED" in event_types
    executor.shutdown()


def test_retry_then_success(store):
    registry, bus, budget, executor = make_executor(store)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")
        return "recovered"

    registry.register(
        ToolSpec(
            name="flaky",
            description="d",
            risk=RiskLevel.READ,
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.01),
        ),
        handler=flaky,
    )

    result = executor.call("flaky")
    assert result == "recovered"
    assert attempts["n"] == 2
    executor.shutdown()


def test_timeout_raises_tool_timeout_error(store):
    registry, bus, budget, executor = make_executor(store)
    registry.register(
        ToolSpec(name="slow", description="d", risk=RiskLevel.READ, timeout_seconds=0.05),
        handler=lambda: time.sleep(1),
    )

    with pytest.raises(ToolTimeoutError):
        executor.call("slow")
    executor.shutdown()
