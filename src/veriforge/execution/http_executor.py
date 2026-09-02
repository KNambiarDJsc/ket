"""HTTP Executor (spec §6, §11 EXECUTOR agent): performs the concrete HTTP
call sequence an invariant implies, against a live target.

Five executable shapes so far (see `experiment_runner.is_executable` for
the exact gate): `execute_authorization_check` (expected=="denied"),
`execute_allowed_only_for_actor_check` (the positive counterpart —
expected=="allowed_only_for_this_actor"), `execute_data_invariant_check`
(expected_status/forbidden_status), and Phase 10's
`execute_endpoint_exposure_check` / `execute_creation_visibility_check`
(contract=="endpoint_exposed" / "creation_visible_in_listing" — see
requirements/invariants.py's `_extract_contract`). All but the last two
require a resolvable (method, path) endpoint match via Phase 3/5's
`match_endpoint_for_requirement`; the contract shapes name their endpoint
literally in the requirement text instead (`world_model.builder.
resolve_literal_endpoint`). Temporal and ordering invariants have no
executor yet — left for a future phase.

Authorization simulation is a documented MVP assumption: the actor's role
is sent via an `X-Role` header — the convention this project's own example
app happens to use. Real multi-identity/session-based auth simulation
(cookies, JWTs, OAuth) is future work (spec §40's
`multiple_test_identities` requirement).
"""
from __future__ import annotations

import json as json_module
from dataclasses import dataclass
from urllib.parse import urlsplit

from veriforge.domain.models import ApiEndpoint, Observation, Requirement
from veriforge.harness.executor import ToolExecutor
from veriforge.world_model.builder import object_keyword

ACTION_TO_HTTP_TOOL = {
    "DELETE": "api.delete",
    "POST": "api.post",
    "PUT": "api.put",
    "GET": "api.get",
}


def origin_of(url: str) -> str:
    """Reduces a URL to its origin (scheme://host:port). Endpoints
    discovered by static analysis (Phase 3) are absolute paths off the
    server root, not off whatever specific page the job's --url happens to
    point the browser explorer at (e.g. a UI entry point like '/ui') — so
    the Executor must call against the origin, not the given URL verbatim."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def safe_json(response) -> object:
    try:
        return response.json()
    except ValueError:
        return None


def _singularize(word: str) -> str:
    """"members" -> "member". Deliberately simplistic — a real actor/role
    vocabulary mapping is application-specific and out of scope here."""
    return word[:-1] if word.endswith("s") and len(word) > 1 else word


def join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def find_creation_endpoint(object_text: str, endpoints: list[ApiEndpoint]) -> ApiEndpoint | None:
    """Finds a POST endpoint to create a throwaway resource for the
    experiment to act on, by the same object-keyword match Phase 3/5 use to
    connect a requirement to an endpoint in the first place."""
    keyword = object_keyword(object_text)
    if not keyword:
        return None
    for ep in endpoints:
        if ep.method == "POST" and keyword in ep.path.lower():
            return ep
    return None


@dataclass
class AuthorizationExecutionResult:
    observations: list[Observation]
    response_status: int
    resource_still_present: bool | None


def execute_authorization_check(
    *,
    base_url: str,
    requirement: Requirement,
    action_endpoint: ApiEndpoint,
    all_endpoints: list[ApiEndpoint],
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> AuthorizationExecutionResult:
    base_url = origin_of(base_url)
    structured = requirement.structured
    actor = structured["actor"]
    object_text = structured["object"]
    observations: list[Observation] = []

    def record(tool: str, action: str, state_before: dict, state_after: dict) -> None:
        observations.append(
            Observation(
                test_run_id=test_run_id, tool=tool, action=action,
                state_before=state_before, state_after=state_after,
            )
        )

    creation_endpoint = find_creation_endpoint(object_text, all_endpoints)
    resource_id = None
    if creation_endpoint is not None:
        create_url = join_url(base_url, creation_endpoint.path)
        resp = tool_executor.call("api.post", url=create_url)
        body = safe_json(resp)
        resource_id = body.get("id") if isinstance(body, dict) else None
        record(
            "api.post", f"POST {creation_endpoint.path} (create a resource to test against)",
            {}, {"status": resp.status_code, "body": body},
        )

    def check_presence() -> bool | None:
        if creation_endpoint is None or resource_id is None:
            return None
        list_url = join_url(base_url, creation_endpoint.path)
        resp = tool_executor.call("api.get", url=list_url)
        body = safe_json(resp)
        record("api.get", f"GET {creation_endpoint.path} (state check)", {}, {"status": resp.status_code, "body": body})
        if body is None:
            return None
        return resource_id in json_module.dumps(body)

    resource_present_before = check_presence()

    action_path = action_endpoint.path.rstrip("/")
    target_path = f"{action_path}/{resource_id}" if resource_id else action_endpoint.path
    action_url = join_url(base_url, target_path)
    role_value = _singularize(actor)
    headers = {"X-Role": role_value}

    tool_name = ACTION_TO_HTTP_TOOL.get(action_endpoint.method)
    if tool_name is None:
        raise ValueError(f"No HTTP tool mapped for method {action_endpoint.method}")

    action_resp = tool_executor.call(tool_name, url=action_url, headers=headers)
    record(
        tool_name,
        f"{action_endpoint.method} {target_path} as role='{role_value}'",
        {"resource_present": resource_present_before},
        {"status": action_resp.status_code, "body": safe_json(action_resp)},
    )

    resource_present_after = check_presence()

    return AuthorizationExecutionResult(
        observations=observations,
        response_status=action_resp.status_code,
        resource_still_present=resource_present_after,
    )


@dataclass
class DataInvariantExecutionResult:
    observations: list[Observation]
    response_status: int


def execute_data_invariant_check(
    *,
    base_url: str,
    action_endpoint: ApiEndpoint,
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> DataInvariantExecutionResult:
    """Calls the action endpoint against a resource id guaranteed not to
    exist — no creation step needed, since the point is to observe the
    not-found path (e.g. "deleting a nonexistent project must return 404,
    not 500")."""
    base_url = origin_of(base_url)
    action_path = action_endpoint.path.rstrip("/")
    target_path = f"{action_path}/nonexistent-00000000"
    action_url = join_url(base_url, target_path)

    tool_name = ACTION_TO_HTTP_TOOL.get(action_endpoint.method)
    if tool_name is None:
        raise ValueError(f"No HTTP tool mapped for method {action_endpoint.method}")

    resp = tool_executor.call(tool_name, url=action_url)
    observation = Observation(
        test_run_id=test_run_id, tool=tool_name,
        action=f"{action_endpoint.method} {target_path} (guaranteed-nonexistent resource)",
        state_before={}, state_after={"status": resp.status_code, "body": safe_json(resp)},
    )
    return DataInvariantExecutionResult(observations=[observation], response_status=resp.status_code)


@dataclass
class AllowedOnlyExecutionResult:
    observations: list[Observation]
    actor_status: int
    actor_resource_gone: bool
    other_status: int
    other_resource_gone: bool


def execute_allowed_only_for_actor_check(
    *,
    base_url: str,
    requirement: Requirement,
    action_endpoint: ApiEndpoint,
    all_endpoints: list[ApiEndpoint],
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> AllowedOnlyExecutionResult:
    """The positive counterpart to execute_authorization_check: create a
    fresh throwaway resource and attempt the action once as the named actor
    (expected to succeed) and once as a distinct "not-<actor>" role
    (expected to be denied) — exclusivity only holds if both are true.
    Uses two separate resources so one attempt's outcome can't contaminate
    the other's presence check."""
    base_url = origin_of(base_url)
    structured = requirement.structured
    actor = structured["actor"]
    object_text = structured["object"]
    observations: list[Observation] = []

    def record(tool: str, action: str, state_after: dict) -> None:
        observations.append(
            Observation(test_run_id=test_run_id, tool=tool, action=action, state_before={}, state_after=state_after)
        )

    creation_endpoint = find_creation_endpoint(object_text, all_endpoints)

    def create_and_act(role_value: str) -> tuple[int, bool | None]:
        resource_id = None
        if creation_endpoint is not None:
            create_url = join_url(base_url, creation_endpoint.path)
            resp = tool_executor.call("api.post", url=create_url)
            body = safe_json(resp)
            resource_id = body.get("id") if isinstance(body, dict) else None
            record(
                "api.post", f"POST {creation_endpoint.path} (create resource for role='{role_value}')",
                {"status": resp.status_code, "body": body},
            )

        action_path = action_endpoint.path.rstrip("/")
        target_path = f"{action_path}/{resource_id}" if resource_id else action_endpoint.path
        action_url = join_url(base_url, target_path)
        tool_name = ACTION_TO_HTTP_TOOL.get(action_endpoint.method)
        if tool_name is None:
            raise ValueError(f"No HTTP tool mapped for method {action_endpoint.method}")

        resp = tool_executor.call(tool_name, url=action_url, headers={"X-Role": role_value})
        record(
            tool_name, f"{action_endpoint.method} {target_path} as role='{role_value}'",
            {"status": resp.status_code, "body": safe_json(resp)},
        )
        status = resp.status_code

        still_present = None
        if creation_endpoint is not None and resource_id is not None:
            list_url = join_url(base_url, creation_endpoint.path)
            list_resp = tool_executor.call("api.get", url=list_url)
            list_body = safe_json(list_resp)
            record(
                "api.get", f"GET {creation_endpoint.path} (state check for role='{role_value}')",
                {"status": list_resp.status_code, "body": list_body},
            )
            still_present = resource_id in json_module.dumps(list_body) if list_body is not None else None

        resource_gone = (still_present is False)
        return status, resource_gone

    actor_status, actor_resource_gone = create_and_act(_singularize(actor))
    other_status, other_resource_gone = create_and_act(f"not-{_singularize(actor)}")

    return AllowedOnlyExecutionResult(
        observations=observations,
        actor_status=actor_status, actor_resource_gone=actor_resource_gone,
        other_status=other_status, other_resource_gone=other_resource_gone,
    )


@dataclass
class EndpointExposureExecutionResult:
    observations: list[Observation]
    response_status: int


def execute_endpoint_exposure_check(
    *,
    base_url: str,
    action_endpoint: ApiEndpoint,
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> EndpointExposureExecutionResult:
    """"The service must expose X at METHOD PATH" (Phase 10, contract==
    "endpoint_exposed"): a single-endpoint reachability contract -- call the
    endpoint exactly as declared and record whether it actually answers. No
    resource creation needed."""
    base_url = origin_of(base_url)
    url = join_url(base_url, action_endpoint.path)
    tool_name = ACTION_TO_HTTP_TOOL.get(action_endpoint.method)
    if tool_name is None:
        raise ValueError(f"No HTTP tool mapped for method {action_endpoint.method}")

    resp = tool_executor.call(tool_name, url=url)
    observation = Observation(
        test_run_id=test_run_id, tool=tool_name,
        action=f"{action_endpoint.method} {action_endpoint.path} (endpoint-exposure contract check)",
        state_before={}, state_after={"status": resp.status_code, "body": safe_json(resp)},
    )
    return EndpointExposureExecutionResult(observations=[observation], response_status=resp.status_code)


def _find_entry_by_id(body: object, resource_id: str) -> dict | None:
    """Recursively searches a JSON response body for a dict entry whose
    "id" field matches -- response envelopes vary (a bare list, or a list
    nested under a named key like {"projects": [...]}), so this doesn't
    assume one particular shape."""
    if isinstance(body, dict):
        if body.get("id") == resource_id:
            return body
        for value in body.values():
            found = _find_entry_by_id(value, resource_id)
            if found is not None:
                return found
    elif isinstance(body, list):
        for item in body:
            found = _find_entry_by_id(item, resource_id)
            if found is not None:
                return found
    return None


@dataclass
class CreationVisibilityExecutionResult:
    observations: list[Observation]
    created_body: dict | None
    listing_entry: dict | None
    schema_mismatches: list[str]


def execute_creation_visibility_check(
    *,
    base_url: str,
    structured: dict,
    all_endpoints: list[ApiEndpoint],
    listing_endpoint: ApiEndpoint,
    tool_executor: ToolExecutor,
    test_run_id: str,
) -> CreationVisibilityExecutionResult:
    """"A newly created X must appear in GET <path> immediately after
    creation" (Phase 10, contract=="creation_visible_in_listing"): a real
    multi-endpoint contract check spanning two independent endpoints --
    POST creates a resource, then GET the named listing endpoint and confirm
    (a) the resource actually shows up and (b) every field the creation
    response returned is still present with the same value in the listing
    entry (a request/response schema-consistency assertion, not just
    presence)."""
    base_url = origin_of(base_url)
    observations: list[Observation] = []

    creation_endpoint = find_creation_endpoint(structured["object"], all_endpoints)
    if creation_endpoint is None:
        return CreationVisibilityExecutionResult(
            observations=observations, created_body=None, listing_entry=None,
            schema_mismatches=["no POST creation endpoint could be resolved for this object"],
        )

    create_url = join_url(base_url, creation_endpoint.path)
    create_resp = tool_executor.call("api.post", url=create_url)
    created_body = safe_json(create_resp)
    observations.append(Observation(
        test_run_id=test_run_id, tool="api.post",
        action=f"POST {creation_endpoint.path} (create resource for contract check)",
        state_before={}, state_after={"status": create_resp.status_code, "body": created_body},
    ))

    resource_id = created_body.get("id") if isinstance(created_body, dict) else None

    listing_url = join_url(base_url, listing_endpoint.path)
    listing_resp = tool_executor.call("api.get", url=listing_url)
    listing_body = safe_json(listing_resp)
    observations.append(Observation(
        test_run_id=test_run_id, tool="api.get",
        action=f"GET {listing_endpoint.path} (contract check: is it visible?)",
        state_before={}, state_after={"status": listing_resp.status_code, "body": listing_body},
    ))

    listing_entry = _find_entry_by_id(listing_body, resource_id) if resource_id else None

    schema_mismatches: list[str] = []
    if isinstance(created_body, dict) and listing_entry is not None:
        for key, value in created_body.items():
            if key not in listing_entry:
                schema_mismatches.append(f"field '{key}' present in creation response but missing from listing entry")
            elif listing_entry[key] != value:
                schema_mismatches.append(
                    f"field '{key}' = {value!r} at creation but {listing_entry[key]!r} in the listing"
                )

    return CreationVisibilityExecutionResult(
        observations=observations, created_body=created_body,
        listing_entry=listing_entry, schema_mismatches=schema_mismatches,
    )
