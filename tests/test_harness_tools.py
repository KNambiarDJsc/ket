import pytest

from veriforge.domain.enums import RiskLevel
from veriforge.harness.tools import (
    ToolAlreadyRegisteredError,
    ToolNotFoundError,
    ToolRegistry,
    ToolSpec,
)


def make_spec(name="tool.a", risk=RiskLevel.READ):
    return ToolSpec(name=name, description="does a thing", risk=risk)


def test_register_and_get():
    registry = ToolRegistry()
    registry.register(make_spec(), handler=lambda: "ok")
    tool = registry.get("tool.a")
    assert tool.handler() == "ok"


def test_duplicate_registration_raises():
    registry = ToolRegistry()
    registry.register(make_spec(), handler=lambda: None)
    with pytest.raises(ToolAlreadyRegisteredError):
        registry.register(make_spec(), handler=lambda: None)


def test_unknown_tool_raises():
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get("does.not.exist")


def test_list_by_risk_filters():
    registry = ToolRegistry()
    registry.register(make_spec("tool.read", RiskLevel.READ), handler=lambda: None)
    registry.register(make_spec("tool.destructive", RiskLevel.DESTRUCTIVE), handler=lambda: None)

    read_tools = registry.list_by_risk(RiskLevel.READ)
    assert [t.name for t in read_tools] == ["tool.read"]
