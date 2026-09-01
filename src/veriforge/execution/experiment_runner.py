"""Ties the HTTP Executor + Oracle together for one Test/Experiment: run
the concrete HTTP sequence its structured invariant implies, judge the
result, and produce everything needed to persist (TestRun, Observations,
updated Test status, optional Finding). Spec §6/§17/§18.

Phase 6 supported exactly one invariant kind (expected=="denied"). Phase 9
adds two more: expected=="allowed_only_for_this_actor" (the positive
counterpart) and data invariants (expected_status/forbidden_status).
`is_executable`/`run_experiment` dispatch on `requirement.structured` to
pick the right Executor+Oracle pair; anything that doesn't match one of
these three shapes stays unexecuted (HYPOTHESIS/PLANNED), honestly, rather
than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.domain.enums import FailureCategory, Verdict
from veriforge.domain.models import ApiEndpoint, Finding, Observation, Requirement, Test, TestRun, utcnow
from veriforge.execution.http_executor import (
    execute_allowed_only_for_actor_check,
    execute_authorization_check,
    execute_data_invariant_check,
)
from veriforge.harness.executor import ToolExecutor
from veriforge.oracle.oracle import (
    OracleVerdict,
    judge_allowed_only_for_actor,
    judge_authorization,
    judge_data_invariant,
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

    else:
        raise ValueError(f"run_experiment called on a non-executable requirement structure: {structured}")

    test_run.finished_at = utcnow()
    test_run.verdict = verdict.verdict
    finding = _build_finding(requirement, test_run, verdict)

    return ExperimentRunResult(test_run=test_run, observations=observations, oracle_verdict=verdict, finding=finding)
