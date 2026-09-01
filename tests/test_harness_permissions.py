import pytest

from veriforge.domain.enums import PermissionDecision, RiskLevel
from veriforge.harness.permissions import PermissionDeniedError, PermissionPolicy
from veriforge.harness.tools import ToolSpec


def spec(risk):
    return ToolSpec(name="t", description="d", risk=risk)


def test_read_and_low_risk_allowed_by_default():
    policy = PermissionPolicy()
    policy.authorize(spec(RiskLevel.READ), {})
    policy.authorize(spec(RiskLevel.LOW_RISK), {})


def test_destructive_denied_by_default():
    policy = PermissionPolicy()
    with pytest.raises(PermissionDeniedError):
        policy.authorize(spec(RiskLevel.DESTRUCTIVE), {})


def test_blocked_never_overridable():
    policy = PermissionPolicy(overrides={RiskLevel.BLOCKED: PermissionDecision.ALLOW})
    with pytest.raises(PermissionDeniedError):
        policy.authorize(spec(RiskLevel.BLOCKED), {})


def test_high_risk_requires_confirmation_denied_without_callback():
    policy = PermissionPolicy()
    with pytest.raises(PermissionDeniedError):
        policy.authorize(spec(RiskLevel.HIGH_RISK), {})


def test_high_risk_confirmation_approved():
    policy = PermissionPolicy(confirm=lambda spec, args: True)
    policy.authorize(spec(RiskLevel.HIGH_RISK), {})  # should not raise


def test_high_risk_confirmation_declined():
    policy = PermissionPolicy(confirm=lambda spec, args: False)
    with pytest.raises(PermissionDeniedError):
        policy.authorize(spec(RiskLevel.HIGH_RISK), {})


def test_override_can_relax_medium_to_deny():
    policy = PermissionPolicy(overrides={RiskLevel.MEDIUM_RISK: PermissionDecision.DENY})
    with pytest.raises(PermissionDeniedError):
        policy.authorize(spec(RiskLevel.MEDIUM_RISK), {})
