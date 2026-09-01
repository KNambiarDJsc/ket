"""Learning Engine (spec §38): a strategy is only ever "kept" on a measured
metric across enough runs — never on an LLM's say-so or a single lucky run.

Today's Phase 6 scope executes exactly one experiment per job run, so a
single run is a very small sample. Rather than pretend that's enough to
judge a Strategy, this records the metric every run and only renders a
keep/revert verdict once `_MIN_RUNS_FOR_DECISION` prior runs exist —
`kept=None` ("insufficient data") is an honest answer, not a guess dressed
up as one. A real statistically-meaningful A/B comparison across many
varied benchmark runs is the Evaluation Lab's job (Phase 17); this is the
mechanism that lab will plug into, not a replacement for it.
"""
from __future__ import annotations

from veriforge.domain.models import Job, Learning, Strategy
from veriforge.storage.repository import Store

_MIN_RUNS_FOR_DECISION = 5


def compute_run_metric(executed_count: int, verdict: str | None) -> float:
    """verified-findings-per-experiment-executed for this run; 0.0 if
    nothing was executed (no live target, or no executable candidate)."""
    if executed_count == 0:
        return 0.0
    return 1.0 if verdict == "FAIL" else 0.0


def record_run_learning(store: Store, project_id: str, strategy: Strategy, job: Job, metric: float) -> Learning:
    prior = [l for l in store.learnings.list_by_project(project_id) if l.measured_metric is not None]
    n = len(prior)
    baseline = sum(l.measured_metric for l in prior) / n if n else None

    if baseline is None or n < _MIN_RUNS_FOR_DECISION:
        kept = None
        reason = (
            f"Only {n} prior run(s) recorded for strategy v{strategy.version}; "
            f"need {_MIN_RUNS_FOR_DECISION} before this metric is meaningful."
        )
    else:
        kept = metric >= baseline
        reason = (
            f"Strategy v{strategy.version}: this run's metric {metric} vs. "
            f"baseline {baseline:.3f} over {n} prior runs."
        )

    learning = Learning(
        project_id=project_id,
        change=f"strategy v{strategy.version} (weights={strategy.weights})",
        reason=reason,
        prediction="verified-findings-per-experiment should meet or exceed the historical baseline",
        baseline_metric=baseline,
        target_metric=(baseline * 1.1) if baseline is not None else None,
        measured_metric=metric,
        kept=kept,
    )
    store.learnings.save(learning, job_id=job.id, project_id=project_id)
    return learning
