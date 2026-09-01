"""Test Scientist / Strategist (spec §8, §11): turns the World Model's open
Unknowns into scored, ranked candidate Experiments — "find the most
informative experiment next."

Phase 5 scope: hypothesis generation + scoring only. Nothing here executes
anything — that's the Executor/Oracle (Phase 6). An experiment ranked #1
here is a *candidate*, not a confirmed test; `promote_to_tests` marks the
top-K as PLANNED and the rest stay HYPOTHESIS, per the Test lifecycle in
spec §24.

Score axes and what backs each one (spec §12's formula):
  coverage                  — is the underlying requirement critical?
  novelty                   — was this Unknown found by live browser
                               exploration (fresher signal) or only static
                               analysis?
  risk                      — requirement kind (AUTHORIZATION/SECURITY
                               weighted highest — these are the categories
                               spec §19 calls out as needing dedicated
                               attention).
  historical_bug_likelihood — real signal from Phase 3: does the Unknown's
                               rationale say the matched endpoint has *no*
                               role/permission-check identifier? That's not
                               a guess, it's what the AST cartographer found.
  information_gain          — does the requirement have a structured
                               invariant (Phase 3) an Oracle could actually
                               check mechanically, vs. only free text?
  change_relevance           — NOT YET COMPUTED. This needs git diff/blame
                               integration (no phase has built that yet), so
                               it's a constant placeholder rather than a
                               guess dressed up as a signal.
  cost                       — requirement kind again: authorization checks
                               need multiple actor identities to test
                               properly, so they cost more than a bare GET.
  redundancy                 — a second Unknown that resolves to the same
                               (method, path) endpoint as one already
                               ranked is penalized, not double-counted.

Weights live in a plain dict (DEFAULT_WEIGHTS) rather than hardcoded into
the formula so a future Learner (Phase 17/25) can persist a tuned Strategy
and pass its weights in here — that's the hook, not built yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from veriforge.domain.enums import RequirementKind, TestStatus
from veriforge.domain.models import Experiment, Requirement, Test, Unknown, WorldModel

DEFAULT_WEIGHTS: dict[str, float] = {
    "coverage": 1.0,
    "novelty": 1.0,
    "risk": 1.0,
    "historical_bug_likelihood": 1.5,
    "information_gain": 1.0,
    "change_relevance": 0.5,
    "cost": 1.0,
    "redundancy": 1.0,
}

_RISK_BY_KIND: dict[RequirementKind, float] = {
    RequirementKind.AUTHORIZATION: 1.0,
    RequirementKind.SECURITY: 1.0,
    RequirementKind.NEGATIVE: 0.8,
    RequirementKind.DATA_INVARIANT: 0.6,
    RequirementKind.ORDERING: 0.5,
    RequirementKind.TEMPORAL: 0.4,
    RequirementKind.FUNCTIONAL: 0.3,
    RequirementKind.UNSPECIFIED: 0.2,
}

_COST_BY_KIND: dict[RequirementKind, float] = {
    RequirementKind.AUTHORIZATION: 0.6,  # needs >=2 actor identities to test properly
    RequirementKind.SECURITY: 0.7,
    RequirementKind.NEGATIVE: 0.5,
    RequirementKind.DATA_INVARIANT: 0.3,
    RequirementKind.ORDERING: 0.5,
    RequirementKind.TEMPORAL: 0.4,
    RequirementKind.FUNCTIONAL: 0.3,
    RequirementKind.UNSPECIFIED: 0.3,
}

_NO_ROLE_CHECK_HINT = "no role/permission-check identifier"
_ENDPOINT_KEY_RE = re.compile(r"Matched to (?P<method>[A-Z]+) (?P<path>\S+)")

_UNCOMPUTED_CHANGE_RELEVANCE = 0.5  # constant until a git-history phase exists


@dataclass
class ScoreBreakdown:
    coverage: float
    novelty: float
    risk: float
    historical_bug_likelihood: float
    information_gain: float
    change_relevance: float
    cost: float
    redundancy: float

    def total(self, weights: dict[str, float]) -> float:
        return (
            weights["coverage"] * self.coverage
            + weights["novelty"] * self.novelty
            + weights["risk"] * self.risk
            + weights["historical_bug_likelihood"] * self.historical_bug_likelihood
            + weights["information_gain"] * self.information_gain
            + weights["change_relevance"] * self.change_relevance
            - weights["cost"] * self.cost
            - weights["redundancy"] * self.redundancy
        )

    def explain(self) -> str:
        return (
            f"coverage={self.coverage:.1f} novelty={self.novelty:.1f} risk={self.risk:.1f} "
            f"bug_signal={self.historical_bug_likelihood:.1f} info_gain={self.information_gain:.1f} "
            f"change_relevance={self.change_relevance:.1f} cost={self.cost:.1f} "
            f"redundancy={self.redundancy:.1f}"
        )


def endpoint_key(rationale: str) -> str | None:
    match = _ENDPOINT_KEY_RE.search(rationale)
    if not match:
        return None
    return f"{match.group('method')} {match.group('path')}"


def score_unknown(
    unknown: Unknown,
    requirement: Requirement | None,
    seen_endpoint_keys: set[str],
) -> ScoreBreakdown:
    kind = requirement.kind if requirement else RequirementKind.UNSPECIFIED
    critical = requirement.critical if requirement else False

    coverage = 1.0 if critical else 0.3
    novelty = 1.0 if "browser exploration" in unknown.rationale else 0.6
    risk = _RISK_BY_KIND.get(kind, 0.3)
    historical_bug_likelihood = 1.0 if _NO_ROLE_CHECK_HINT in unknown.rationale else 0.3
    information_gain = 1.0 if (requirement and requirement.structured) else 0.4
    cost = _COST_BY_KIND.get(kind, 0.4)

    key = endpoint_key(unknown.rationale)
    redundancy = 0.5 if key is not None and key in seen_endpoint_keys else 0.0

    return ScoreBreakdown(
        coverage=coverage,
        novelty=novelty,
        risk=risk,
        historical_bug_likelihood=historical_bug_likelihood,
        information_gain=information_gain,
        change_relevance=_UNCOMPUTED_CHANGE_RELEVANCE,
        cost=cost,
        redundancy=redundancy,
    )


def rank_experiments(
    world_model: WorldModel,
    weights: dict[str, float] | None = None,
) -> list[Experiment]:
    """Scores every open (unresolved) Unknown as a candidate Experiment and
    returns them ranked highest-value first."""
    weights = weights or DEFAULT_WEIGHTS
    requirements_by_id = {r.id: r for r in world_model.requirements}
    seen_endpoint_keys: set[str] = set()
    experiments: list[Experiment] = []

    for unknown in world_model.unknowns:
        if unknown.resolved:
            continue
        requirement = requirements_by_id.get(unknown.requirement_id) if unknown.requirement_id else None
        breakdown = score_unknown(unknown, requirement, seen_endpoint_keys)

        key = endpoint_key(unknown.rationale)
        if key is not None:
            seen_endpoint_keys.add(key)

        hypothesis = f"Verify: {requirement.source_text}" if requirement else unknown.question
        experiments.append(
            Experiment(
                project_id=world_model.project_id,
                hypothesis=hypothesis,
                requirement_id=requirement.id if requirement else None,
                score=round(breakdown.total(weights), 3),
                rationale=f"{breakdown.explain()} | {unknown.rationale}",
            )
        )

    experiments.sort(key=lambda e: e.score, reverse=True)
    return experiments


def promote_to_tests(experiments: list[Experiment], top_k: int = 3) -> list[Test]:
    """Top-K scored experiments become PLANNED tests (next in line to
    execute once Phase 6's Executor exists); the rest stay as HYPOTHESIS —
    recorded, not discarded, in case a future run's budget allows more."""
    tests: list[Test] = []
    for i, experiment in enumerate(experiments):
        status = TestStatus.PLANNED if i < top_k else TestStatus.HYPOTHESIS
        tests.append(
            Test(
                project_id=experiment.project_id,
                experiment_id=experiment.id,
                name=experiment.hypothesis,
                status=status,
            )
        )
    return tests
