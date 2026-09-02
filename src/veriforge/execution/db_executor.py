"""DB Executor (spec §6, §11 EXECUTOR agent; Phase 11 Database Observation):
performs a direct, read-only database read to verify state independently of
the application's own API -- the gap Phase 6's Level-3 state check (a
follow-up GET) can't close, since a follow-up GET only proves what the
*application* is willing to report, not what actually happened to the data.

`run_read_only_query` is the harness-registered primitive
(`database.query_sqlite`); it refuses anything but a SELECT so this stays a
read-only observation tool, never a mutation path -- consistent with every
other DESTRUCTIVE-risk boundary this project draws elsewhere (see
harness/builtin_tools.py's api.post/put/delete commentary).

`execute_db_removal_check` is the one executable shape so far
(structured["db_check"]=="removed_after_delete" -- see
requirements/invariants.py's `_extract_db_check`): create a resource via the
API, delete it via the API, then read the raw table row directly and
confirm it's actually gone, not merely hidden from the API's own read path.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from veriforge.domain.models import ApiEndpoint, Observation, Requirement
from veriforge.execution.http_executor import (
    ACTION_TO_HTTP_TOOL,
    find_creation_endpoint,
    join_url,
    origin_of,
    safe_json,
)
from veriforge.harness.executor import ToolExecutor
from veriforge.world_model.builder import object_keyword

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def run_read_only_query(db_path: str, query: str, params: list | None = None) -> list[dict]:
    """The only database primitive this project exposes: refuses anything
    that isn't a SELECT, so it can only ever observe state, never change it.
    """
    if not query.strip().upper().startswith("SELECT"):
        raise ValueError("run_read_only_query only permits read-only SELECT statements")
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params or [])
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


@dataclass
class DbRemovalExecutionResult:
    observations: list[Observation]
    api_delete_status: int
    row_still_in_db: bool


def execute_db_removal_check(
    *,
    base_url: str,
    db_path: str,
    requirement: Requirement,
    action_endpoint: ApiEndpoint,
    all_endpoints: list[ApiEndpoint],
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> DbRemovalExecutionResult:
    base_url = origin_of(base_url)
    structured = requirement.structured
    object_text = structured["object"]
    observations: list[Observation] = []

    table = object_keyword(object_text)
    if not table or not _TABLE_NAME_RE.match(table):
        raise ValueError(f"cannot safely resolve a table name from requirement object {object_text!r}")

    creation_endpoint = find_creation_endpoint(object_text, all_endpoints)
    resource_id = None
    if creation_endpoint is not None:
        create_url = join_url(base_url, creation_endpoint.path)
        resp = tool_executor.call("api.post", url=create_url)
        body = safe_json(resp)
        resource_id = body.get("id") if isinstance(body, dict) else None
        observations.append(Observation(
            test_run_id=test_run_id, tool="api.post",
            action=f"POST {creation_endpoint.path} (create resource for DB-removal check)",
            state_before={}, state_after={"status": resp.status_code, "body": body},
        ))

    action_path = action_endpoint.path.rstrip("/")
    target_path = f"{action_path}/{resource_id}" if resource_id else action_endpoint.path
    action_url = join_url(base_url, target_path)
    tool_name = ACTION_TO_HTTP_TOOL.get(action_endpoint.method)
    if tool_name is None:
        raise ValueError(f"No HTTP tool mapped for method {action_endpoint.method}")

    action_resp = tool_executor.call(tool_name, url=action_url)
    observations.append(Observation(
        test_run_id=test_run_id, tool=tool_name,
        action=f"{action_endpoint.method} {target_path} (delete via the API)",
        state_before={}, state_after={"status": action_resp.status_code, "body": safe_json(action_resp)},
    ))

    rows = tool_executor.call(
        "database.query_sqlite", db_path=db_path,
        query=f"SELECT COUNT(*) AS cnt FROM {table} WHERE id = ?", params=[resource_id],
    )
    row_count = rows[0]["cnt"] if rows else 0
    observations.append(Observation(
        test_run_id=test_run_id, tool="database.query_sqlite",
        action=f"SELECT COUNT(*) FROM {table} WHERE id = ? (direct DB state check, bypassing the API)",
        state_before={}, state_after={"row_count": row_count},
    ))

    return DbRemovalExecutionResult(
        observations=observations,
        api_delete_status=action_resp.status_code,
        row_still_in_db=row_count > 0,
    )
