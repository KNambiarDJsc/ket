"""Reproducer (spec §11/§18): re-runs the exact same experiment once more
against the live target. Agreement between the two runs is what lets a
Finding graduate to BUG_VERIFIED instead of staying merely TRIAGED;
disagreement is real signal (FLAKINESS), not noise to discard.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.domain.enums import Verdict
from veriforge.domain.models import ApiEndpoint, Requirement, Test
from veriforge.execution.experiment_runner import ExperimentRunResult, run_experiment
from veriforge.harness.executor import ToolExecutor


@dataclass
class ReproductionResult:
    reproducible: bool
    second_run: ExperimentRunResult


def reproduce(
    *,
    base_url: str,
    requirement: Requirement,
    endpoint: ApiEndpoint,
    all_endpoints: list[ApiEndpoint],
    tool_executor: ToolExecutor,
    test: Test,
    first_verdict: Verdict,
    db_path: str | None = None,
) -> ReproductionResult:
    second_run = run_experiment(
        base_url=base_url,
        requirement=requirement,
        endpoint=endpoint,
        all_endpoints=all_endpoints,
        tool_executor=tool_executor,
        test=test,
        db_path=db_path,
    )
    return ReproductionResult(
        reproducible=(second_run.oracle_verdict.verdict == first_verdict),
        second_run=second_run,
    )
