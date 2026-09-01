"""ToolExecutor: the only path through which a tool handler actually runs.

Ties together the registry (what can be called), the permission policy
(whether it's allowed), the budget tracker (whether there's room left), and
the event bus (so every call is observable per the event schema in spec
§1: run_id/agent/action/target/observation/result/latency_ms). Timeouts and
retries are enforced here, not left to individual handlers.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from veriforge.domain.enums import EventType
from veriforge.events.bus import EventBus
from veriforge.harness.budget import BudgetExceededError, BudgetTracker
from veriforge.harness.permissions import PermissionDeniedError, PermissionPolicy
from veriforge.harness.tools import ToolRegistry


class ToolTimeoutError(Exception):
    pass


def _summarize(value: Any, max_len: int = 400) -> str:
    text = repr(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        budget: BudgetTracker,
        bus: EventBus,
        job_id: str,
        agent_name: str = "harness",
    ):
        self._registry = registry
        self._policy = policy
        self._budget = budget
        self._bus = bus
        self._job_id = job_id
        self._agent_name = agent_name
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="veriforge-tool")

    def call(self, tool_name: str, /, **kwargs: Any) -> Any:
        tool = self._registry.get(tool_name)  # raises ToolNotFoundError

        try:
            self._policy.authorize(tool.spec, kwargs)
        except PermissionDeniedError as exc:
            self._bus.publish(
                self._job_id,
                EventType.TOOL_CALL_DENIED,
                {"agent": self._agent_name, "action": tool_name, "target": _summarize(kwargs), "reason": str(exc)},
            )
            raise

        try:
            self._budget.record_tool_call()
        except BudgetExceededError as exc:
            self._bus.publish(
                self._job_id,
                EventType.BUDGET_EXCEEDED,
                {"agent": self._agent_name, "action": tool_name, "reason": str(exc)},
            )
            raise

        self._bus.publish(
            self._job_id,
            EventType.TOOL_CALL_STARTED,
            {"agent": self._agent_name, "action": tool_name, "target": _summarize(kwargs)},
        )

        retry_policy = tool.spec.retry_policy
        attempts = retry_policy.max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            start = time.monotonic()
            future = self._pool.submit(tool.handler, **kwargs)
            try:
                result = future.result(timeout=tool.spec.timeout_seconds)
            except FutureTimeoutError as exc:
                last_exc = ToolTimeoutError(
                    f"tool '{tool_name}' exceeded timeout of {tool.spec.timeout_seconds}s"
                )
                latency_ms = (time.monotonic() - start) * 1000
                self._bus.publish(
                    self._job_id,
                    EventType.TOOL_CALL_FAILED,
                    {
                        "agent": self._agent_name,
                        "action": tool_name,
                        "attempt": attempt,
                        "error": str(last_exc),
                        "latency_ms": latency_ms,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - genuinely any handler error is reportable
                last_exc = exc
                latency_ms = (time.monotonic() - start) * 1000
                self._bus.publish(
                    self._job_id,
                    EventType.TOOL_CALL_FAILED,
                    {
                        "agent": self._agent_name,
                        "action": tool_name,
                        "attempt": attempt,
                        "error": str(exc),
                        "latency_ms": latency_ms,
                    },
                )
            else:
                latency_ms = (time.monotonic() - start) * 1000
                self._bus.publish(
                    self._job_id,
                    EventType.TOOL_CALL_SUCCEEDED,
                    {
                        "agent": self._agent_name,
                        "action": tool_name,
                        "observation": _summarize(result),
                        "latency_ms": latency_ms,
                        "attempt": attempt,
                    },
                )
                return result

            if attempt < attempts:
                time.sleep(retry_policy.backoff_seconds)

        assert last_exc is not None
        raise last_exc

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
