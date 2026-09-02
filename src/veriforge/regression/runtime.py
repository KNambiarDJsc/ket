"""Standalone harness construction for a generated regression test (Phase
13): every Executor function since Phase 6 needs a real `ToolExecutor`
(registry + permissions + budget + event bus), but a generated regression
test can't depend on VeriForge's own job lifecycle or this repo's pytest
fixtures -- it has to run standalone, wherever the target project's own
test suite eventually runs it. This builds the same machinery fresh,
in-memory, with no persistence needed beyond the test's own lifetime.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from veriforge.domain.models import new_id
from veriforge.events.bus import EventBus
from veriforge.harness.budget import BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.llm.provider import NullLLMProvider
from veriforge.storage.repository import Store
from veriforge.storage.schema import create_all


def make_standalone_tool_executor(job_id: str | None = None) -> ToolExecutor:
    job_id = job_id or new_id("regression")
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    store = Store(session)
    bus = EventBus(store)
    budget = BudgetTracker.new(job_id)
    registry = ToolRegistry()
    register_builtin_tools(registry, NullLLMProvider())
    return ToolExecutor(registry, PermissionPolicy(), budget, bus, job_id, agent_name="regression_test")
