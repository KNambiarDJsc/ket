"""Tool registry.

Every capability an agent can use is a registered Tool with a declared risk
level, timeout, and retry policy — never a bare function an agent calls
directly. The registry is pure bookkeeping; enforcement (permissions,
budget) happens in executor.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from veriforge.domain.enums import RiskLevel


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 0
    backoff_seconds: float = 0.0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sandbox_required: bool = False


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: ToolHandler


class ToolAlreadyRegisteredError(Exception):
    pass


class ToolNotFoundError(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ToolAlreadyRegisteredError(f"Tool '{spec.name}' is already registered")
        self._tools[spec.name] = Tool(spec=spec, handler=handler)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"No tool registered as '{name}'") from exc

    def list(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def list_by_risk(self, risk: RiskLevel) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values() if t.spec.risk == risk]
