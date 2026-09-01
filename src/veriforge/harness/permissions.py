"""Permission enforcement.

The harness — not the calling agent/LLM — decides whether a tool call may
proceed. A PermissionPolicy resolves a ToolSpec's risk level to a decision;
REQUIRES_CONFIRMATION only proceeds if an explicit confirm callback approves
it, and defaults to DENY otherwise (fail safe, per spec §8/§1 Principle 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from veriforge.domain.enums import DEFAULT_RISK_POLICY, PermissionDecision, RiskLevel
from veriforge.harness.tools import ToolSpec

ConfirmCallback = Callable[[ToolSpec, dict], bool]


class PermissionDeniedError(Exception):
    def __init__(self, tool_name: str, risk: RiskLevel, reason: str):
        self.tool_name = tool_name
        self.risk = risk
        self.reason = reason
        super().__init__(f"Permission denied for tool '{tool_name}' (risk={risk.value}): {reason}")


@dataclass
class PermissionPolicy:
    """`overrides` lets a project raise/lower the default decision for a risk
    tier (e.g. allow HIGH_RISK unattended in a sandboxed CI run) without
    touching the fail-safe defaults for everyone else."""

    overrides: dict[RiskLevel, PermissionDecision] = field(default_factory=dict)
    confirm: ConfirmCallback | None = None

    def decide(self, spec: ToolSpec, args: dict) -> PermissionDecision:
        if spec.risk == RiskLevel.BLOCKED:
            return PermissionDecision.DENY  # never overridable
        return self.overrides.get(spec.risk, DEFAULT_RISK_POLICY[spec.risk])

    def authorize(self, spec: ToolSpec, args: dict) -> None:
        """Raises PermissionDeniedError if the call may not proceed."""
        decision = self.decide(spec, args)
        if decision == PermissionDecision.ALLOW:
            return
        if decision == PermissionDecision.REQUIRES_CONFIRMATION and self.confirm is not None:
            if self.confirm(spec, args):
                return
            raise PermissionDeniedError(spec.name, spec.risk, "confirmation declined")
        if decision == PermissionDecision.REQUIRES_CONFIRMATION:
            raise PermissionDeniedError(
                spec.name, spec.risk, "requires confirmation but no confirm callback is configured"
            )
        raise PermissionDeniedError(spec.name, spec.risk, "denied by policy")
