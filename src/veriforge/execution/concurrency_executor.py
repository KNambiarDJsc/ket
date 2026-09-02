"""Concurrency Executor (spec §6, §11 EXECUTOR agent; Phase 15 Security +
Concurrency): the one executable shape so far
(structured["concurrency_check"]=="no_duplicate_on_creation_replay" -- see
requirements/invariants.py's `_extract_concurrency_check`).

This is the first Executor to compose two earlier phases' capabilities
rather than add a new primitive: Phase 14's `FaultInjectingProxy`
(`duplicate_paths`) actually delivers one client request to the backend
twice, and Phase 11's direct-database read counts the real resulting rows --
an API response alone can't tell "one resource created" apart from "two
resources created, one response discarded by the network," which is exactly
the ambiguity a duplicated request creates. Needs a real `db_path`, gated
the same way Phase 11's db_check is (see job_runner._execute_top_experiment).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from veriforge.domain.models import ApiEndpoint, Observation, Requirement
from veriforge.environment.fault_proxy import FaultConfig, FaultInjectingProxy
from veriforge.execution.http_executor import join_url, origin_of, safe_json
from veriforge.harness.executor import ToolExecutor
from veriforge.world_model.builder import object_keyword

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _row_count(tool_executor: ToolExecutor, db_path: str, table: str) -> int:
    rows = tool_executor.call("database.query_sqlite", db_path=db_path, query=f"SELECT COUNT(*) AS cnt FROM {table}")
    return rows[0]["cnt"] if rows else 0


@dataclass
class DuplicateCreationExecutionResult:
    observations: list[Observation]
    row_count_delta: int


def execute_duplicate_creation_check(
    *,
    base_url: str,
    db_path: str,
    requirement: Requirement,
    action_endpoint: ApiEndpoint,
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> DuplicateCreationExecutionResult:
    base_url = origin_of(base_url)
    structured = requirement.structured
    observations: list[Observation] = []

    table = object_keyword(structured["object"])
    if not table or not _TABLE_NAME_RE.match(table):
        raise ValueError(f"cannot safely resolve a table name from requirement object {structured['object']!r}")

    count_before = _row_count(tool_executor, db_path, table)
    observations.append(Observation(
        test_run_id=test_run_id, tool="database.query_sqlite",
        action=f"SELECT COUNT(*) FROM {table} (baseline, before the duplicated request)",
        state_before={}, state_after={"row_count": count_before},
    ))

    # 127.0.0.1, not whatever host base_url names: the proxy makes its own
    # outbound httpx calls to the backend, and on Windows "localhost" can add
    # a multi-second IPv6-then-IPv4 resolution delay per hop (see
    # environment/fault_proxy.py and tests/test_fault_proxy.py) -- harmless
    # for correctness but needlessly slow for a check that already makes two
    # backend round trips by design.
    proxy_backend = base_url.replace("localhost", "127.0.0.1")
    proxy = FaultInjectingProxy(proxy_backend, FaultConfig(duplicate_paths={action_endpoint.path}))
    proxy_url = proxy.start()
    try:
        create_url = join_url(proxy_url, action_endpoint.path)
        resp = tool_executor.call("api.post", url=create_url)
        observations.append(Observation(
            test_run_id=test_run_id, tool="api.post",
            action=(
                f"POST {action_endpoint.path} through a fault-injecting proxy configured to deliver "
                "this request to the backend twice (simulating a flaky-network retry)"
            ),
            state_before={}, state_after={"status": resp.status_code, "body": safe_json(resp)},
        ))
    finally:
        proxy.stop()

    count_after = _row_count(tool_executor, db_path, table)
    observations.append(Observation(
        test_run_id=test_run_id, tool="database.query_sqlite",
        action=f"SELECT COUNT(*) FROM {table} (after the duplicated request, direct DB read)",
        state_before={}, state_after={"row_count": count_after},
    ))

    return DuplicateCreationExecutionResult(
        observations=observations,
        row_count_delta=count_after - count_before,
    )
