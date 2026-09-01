"""Budget enforcement.

Wraps a persisted LoopState so consumption survives crashes/restarts (the
harness principle "state must survive crashes" — §1 Principle 1, §16). The
tracker is deliberately dumb: it only compares counters against limits. What
counts against the budget (a tool call, N tokens) is decided by the caller
(ToolExecutor).
"""
from __future__ import annotations

import time

from veriforge.domain.models import LoopState


class BudgetExceededError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class BudgetTracker:
    def __init__(
        self,
        loop_state: LoopState,
        *,
        max_tool_calls: int | None = None,
        max_runtime_seconds: float | None = None,
    ):
        self.state = loop_state
        self.max_tool_calls = max_tool_calls
        self.max_runtime_seconds = max_runtime_seconds
        self.tool_calls_used = 0
        self._start_monotonic = time.monotonic()

    @classmethod
    def new(
        cls,
        job_id: str,
        *,
        max_iterations: int | None = None,
        max_tokens: int | None = None,
        max_tool_calls: int | None = None,
        max_runtime_seconds: float | None = None,
    ) -> "BudgetTracker":
        loop_state = LoopState(job_id=job_id, max_iterations=max_iterations, max_tokens=max_tokens)
        return cls(loop_state, max_tool_calls=max_tool_calls, max_runtime_seconds=max_runtime_seconds)

    def check(self) -> None:
        """Raises BudgetExceededError if any limit has already been passed."""
        if self.state.max_tokens is not None and self.state.tokens_used > self.state.max_tokens:
            raise BudgetExceededError(
                f"token budget exceeded: {self.state.tokens_used}/{self.state.max_tokens}"
            )
        if self.max_tool_calls is not None and self.tool_calls_used > self.max_tool_calls:
            raise BudgetExceededError(
                f"tool-call budget exceeded: {self.tool_calls_used}/{self.max_tool_calls}"
            )
        if self.max_runtime_seconds is not None:
            elapsed = self.elapsed_seconds()
            if elapsed > self.max_runtime_seconds:
                raise BudgetExceededError(
                    f"runtime budget exceeded: {elapsed:.1f}s/{self.max_runtime_seconds}s"
                )

    def record_tool_call(self) -> None:
        self.tool_calls_used += 1
        self.check()

    def record_tokens(self, n: int) -> None:
        self.state.tokens_used += n
        self.check()

    def remaining_tool_calls(self) -> int | None:
        if self.max_tool_calls is None:
            return None
        return max(0, self.max_tool_calls - self.tool_calls_used)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_monotonic
