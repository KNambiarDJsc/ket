"""Evaluation Lab gate (Phase 16, spec §42): decides whether a harness
change (an Executor/Oracle/requirements-extraction change) may be kept,
based on a real comparison against the ground-truth benchmark suite --
never on a single unlabeled run, and never claiming more statistical
confidence than the benchmark suite's actual size supports.

This is the mechanism `learning/engine.py`'s own docstring names as
missing. Phase 8's Strategy keep/revert gate needs `_MIN_RUNS_FOR_DECISION`
real production runs before it renders a verdict at all -- organic
accumulation against live traffic, which could take weeks for a low-
traffic project. This gate answers a different, narrower question
immediately: "does a candidate harness still find every known bug and
raise no new false alarms against what we already know the answer to,"
using the Harness Auditor's benchmark suite instead of waiting on live
runs. It's a pre-deployment check, not a replacement for Phase 8's
ongoing, production-truth gate -- a harness could pass this and still earn
a `kept=False` from Phase 8 later if it turns out to underperform on real,
unlabeled traffic the benchmark suite doesn't represent.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.evaluation.harness_auditor import BenchmarkResult, aggregate_metrics

# Mirrors learning/engine.py's own _MIN_RUNS_FOR_DECISION threshold: "5" is
# this project's established bar for "enough samples to act on," not a new
# number invented for this gate.
_MIN_SCORED_REQUIREMENTS = 5


@dataclass
class GateVerdict:
    kept: bool | None  # None == too few scored requirements to judge
    reason: str
    baseline_metrics: dict[str, float]
    candidate_metrics: dict[str, float]
    regressions: list[str]


def evaluate_candidate(
    baseline_results: list[BenchmarkResult],
    candidate_results: list[BenchmarkResult],
) -> GateVerdict:
    """Compares a candidate harness's benchmark run against a baseline run
    of the same benchmark suite (before/after the change under test). Kept
    only if the candidate never finds fewer true positives, never raises
    more false positives, and never loses decisiveness (more UNCERTAINs)
    than the baseline -- any single regression is a hard block, since a
    change that trades one known bug for one new false alarm is not an
    improvement no matter what an aggregate score says.
    """
    baseline = aggregate_metrics(baseline_results)
    candidate = aggregate_metrics(candidate_results)

    if baseline["scored_requirement_count"] < _MIN_SCORED_REQUIREMENTS:
        return GateVerdict(
            kept=None,
            reason=(
                f"Only {int(baseline['scored_requirement_count'])} scored requirement(s) in the benchmark "
                f"suite; need at least {_MIN_SCORED_REQUIREMENTS} before a comparison means anything."
            ),
            baseline_metrics=baseline, candidate_metrics=candidate, regressions=[],
        )

    regressions: list[str] = []
    if candidate["verified_findings_per_compute"] < baseline["verified_findings_per_compute"]:
        regressions.append(
            "verified_findings_per_compute dropped "
            f"({baseline['verified_findings_per_compute']:.3f} -> {candidate['verified_findings_per_compute']:.3f})"
        )
    if candidate["false_positive_rate"] > baseline["false_positive_rate"]:
        regressions.append(
            f"false_positive_rate rose ({baseline['false_positive_rate']:.3f} -> {candidate['false_positive_rate']:.3f})"
        )
    if candidate["information_gain_per_experiment"] < baseline["information_gain_per_experiment"]:
        regressions.append(
            "information_gain_per_experiment dropped "
            f"({baseline['information_gain_per_experiment']:.3f} -> {candidate['information_gain_per_experiment']:.3f})"
        )

    kept = len(regressions) == 0
    reason = (
        "No regression on any of the three tracked metrics against the ground-truth benchmark suite."
        if kept
        else "Regression(s) against the ground-truth benchmark suite: " + "; ".join(regressions)
    )
    return GateVerdict(
        kept=kept, reason=reason, baseline_metrics=baseline, candidate_metrics=candidate, regressions=regressions,
    )
