import pytest

from veriforge.harness.budget import BudgetExceededError, BudgetTracker


def test_tool_call_budget_enforced():
    tracker = BudgetTracker.new("job_1", max_tool_calls=2)
    tracker.record_tool_call()
    tracker.record_tool_call()
    with pytest.raises(BudgetExceededError):
        tracker.record_tool_call()


def test_token_budget_enforced():
    tracker = BudgetTracker.new("job_1", max_tokens=100)
    tracker.record_tokens(60)
    with pytest.raises(BudgetExceededError):
        tracker.record_tokens(50)


def test_unbounded_budget_never_raises():
    tracker = BudgetTracker.new("job_1")
    for _ in range(1000):
        tracker.record_tool_call()
    tracker.record_tokens(1_000_000)


def test_remaining_tool_calls():
    tracker = BudgetTracker.new("job_1", max_tool_calls=5)
    tracker.record_tool_call()
    tracker.record_tool_call()
    assert tracker.remaining_tool_calls() == 3
