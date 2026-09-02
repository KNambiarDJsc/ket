"""Ties the HTTP Executor + Oracle together for one Test/Experiment: run
the concrete HTTP sequence its structured invariant implies, judge the
result, and produce everything needed to persist (TestRun, Observations,
updated Test status, optional Finding). Spec §6/§17/§18.

Phase 6 supported exactly one invariant kind (expected=="denied"). Phase 9
adds two more: expected=="allowed_only_for_this_actor" (the positive
counterpart) and data invariants (expected_status/forbidden_status). Phase
10 adds two API/integration-contract kinds keyed by `structured["contract"]`:
"endpoint_exposed" (single-endpoint reachability) and
"creation_visible_in_listing" (a real multi-endpoint contract: create, then
confirm visibility *and* response-schema consistency elsewhere). Phase 11
adds `structured["db_check"]=="removed_after_delete"`: a direct database
read, not another API call -- the one shape that needs an optional
`db_path` threaded through (only a job that was given `--db-path` can ever
execute it; see job_runner._execute_top_experiment's gate). Phase 15 adds
`structured["concurrency_check"]=="no_duplicate_on_creation_replay"`:
composes Phase 14's FaultInjectingProxy (duplicate delivery) with Phase 11's
direct-DB read (row count) -- also gated on `db_path` like the db_check
shape.
`is_executable`/`run_experiment` dispatch on `requirement.structured` to
pick the right Executor+Oracle pair; anything that doesn't match one of
these seven shapes stays unexecuted (HYPOTHESIS/PLANNED), honestly, rather
than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.domain.enums import FailureCategory, Verdict
from veriforge.domain.models import ApiEndpoint, Finding, Observation, Requirement, Test, TestRun, utcnow
from veriforge.execution.concurrency_executor import execute_duplicate_creation_check
from veriforge.execution.db_executor import execute_db_removal_check
from veriforge.execution.http_executor import (
    execute_allowed_only_for_actor_check,
    execute_authorization_check,
    execute_creation_visibility_check,
    execute_data_invariant_check,
    execute_endpoint_exposure_check,
)
from veriforge.harness.executor import ToolExecutor
from veriforge.oracle.oracle import (
    OracleVerdict,
    judge_allowed_only_for_actor,
    judge_authorization,
    judge_creation_visibility,
    judge_data_invariant,
    judge_db_removal,
    judge_duplicate_creation,
    judge_endpoint_exposure,
)


@dataclass
class ExperimentRunResult:
    test_run: TestRun
    observations: list[Observation]
    oracle_verdict: OracleVerdict
    finding: Finding | None


def is_executable(requirement: Requirement | None) -> bool:
    if requirement is None or not requirement.structured:
        return False
    structured = requirement.structured
    expected = structured.get("expected")
    if expected == "denied":
        return True
    if expected == "allowed_only_for_this_actor":
        return "actor" in structured and "object" in structured
    if "expected_status" in structured:
        # A data-invariant check still needs a resolvable endpoint, which
        # needs action/object -- match_endpoint_for_requirement enforces
        # that separately; here we only gate on the invariant shape itself.
        return "action" in structured and "object" in structured
    contract = structured.get("contract")
    if contract == "endpoint_exposed":
        return "method" in structured and "path" in structured
    if contract == "creation_visible_in_listing":
        return "object" in structured and "method" in structured and "path" in structured
    if structured.get("db_check") == "removed_after_delete":
        return "action" in structured and "object" in structured
    if structured.get("concurrency_check") == "no_duplicate_on_creation_replay":
        return "action" in structured and "object" in structured
    return False


def _build_finding(requirement: Requirement, test_run: TestRun, verdict: OracleVerdict) -> Finding | None:
    # Category is UNKNOWN here on purpose: classifying it properly (spec §18's
    # failure taxonomy) is the Triager's job (Phase 7, investigation/triager.py),
    # which always runs immediately after whenever this produces a Finding.
    if verdict.verdict != Verdict.FAIL:
        return None
    return Finding(
        project_id=requirement.project_id,
        test_run_id=test_run.id,
        category=FailureCategory.UNKNOWN,
        summary=f"{requirement.source_text} — VIOLATED: {verdict.reasoning}",
        confidence=verdict.confidence,
        requirement_id=requirement.id,
    )


def run_experiment(
    *,
    base_url: str,
    requirement: Requirement,
    endpoint: ApiEndpoint,
    all_endpoints: list[ApiEndpoint],
    tool_executor: ToolExecutor,
    test: Test,
    db_path: str | None = None,
) -> ExperimentRunResult:
    structured = requirement.structured
    expected = structured.get("expected")
    test_run = TestRun(test_id=test.id)

    if expected == "denied":
        result = execute_authorization_check(
            base_url=base_url, requirement=requirement, action_endpoint=endpoint,
            all_endpoints=all_endpoints, tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_authorization(
            expected=expected, response_status=result.response_status,
            resource_still_present=result.resource_still_present,
        )
        observations = result.observations

    elif expected == "allowed_only_for_this_actor":
        result = execute_allowed_only_for_actor_check(
            base_url=base_url, requirement=requirement, action_endpoint=endpoint,
            all_endpoints=all_endpoints, tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_allowed_only_for_actor(
            actor_status=result.actor_status, actor_resource_gone=result.actor_resource_gone,
            other_status=result.other_status, other_resource_gone=result.other_resource_gone,
        )
        observations = result.observations

    elif "expected_status" in structured:
        result = execute_data_invariant_check(
            base_url=base_url, action_endpoint=endpoint,
            tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_data_invariant(
            expected_status=structured["expected_status"],
            forbidden_status=structured.get("forbidden_status"),
            response_status=result.response_status,
        )
        observations = result.observations

    elif structured.get("contract") == "endpoint_exposed":
        result = execute_endpoint_exposure_check(
            base_url=base_url, action_endpoint=endpoint,
            tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_endpoint_exposure(
            expected_method=structured["method"], expected_path=structured["path"],
            response_status=result.response_status,
        )
        observations = result.observations

    elif structured.get("contract") == "creation_visible_in_listing":
        result = execute_creation_visibility_check(
            base_url=base_url, structured=structured, all_endpoints=all_endpoints,
            listing_endpoint=endpoint, tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_creation_visibility(
            listing_entry=result.listing_entry, schema_mismatches=result.schema_mismatches,
        )
        observations = result.observations

    elif structured.get("db_check") == "removed_after_delete":
        if db_path is None:
            raise ValueError("db_check requirement requires a db_path but none was provided")
        result = execute_db_removal_check(
            base_url=base_url, db_path=db_path, requirement=requirement, action_endpoint=endpoint,
            all_endpoints=all_endpoints, tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_db_removal(row_still_in_db=result.row_still_in_db)
        observations = result.observations

    elif structured.get("concurrency_check") == "no_duplicate_on_creation_replay":
        if db_path is None:
            raise ValueError("concurrency_check requirement requires a db_path but none was provided")
        result = execute_duplicate_creation_check(
            base_url=base_url, db_path=db_path, requirement=requirement, action_endpoint=endpoint,
            tool_executor=tool_executor, test_run_id=test_run.id,
        )
        verdict = judge_duplicate_creation(row_count_delta=result.row_count_delta)
        observations = result.observations

    else:
        raise ValueError(f"run_experiment called on a non-executable requirement structure: {structured}")

    test_run.finished_at = utcnow()
    test_run.verdict = verdict.verdict
    finding = _build_finding(requirement, test_run, verdict)

    return ExperimentRunResult(test_run=test_run, observations=observations, oracle_verdict=verdict, finding=finding)
