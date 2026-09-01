"""Semantic memory: facts already established about this project from prior
runs — specifically, "has this requirement already been confirmed violated
(or verified okay) by a past run's Finding?" so a later run doesn't re-flag
an already-answered question as a fresh Unknown.

Deliberately exact-key lookup (by requirement_id), not embedding similarity
search — nomic-embed-text is pulled locally and reserved for when the system
actually needs "find findings *similar* to this one"; that's not this.
"""
from __future__ import annotations

from veriforge.domain.models import Finding, WorldModel
from veriforge.storage.repository import Store


def prior_findings_by_requirement(store: Store, project_id: str) -> dict[str, Finding]:
    """Maps requirement_id -> its most recent prior Finding, across all past
    runs of this project. Relies on Store returning rows in insertion order
    (true for the SQLite-backed TypedRepository today); if that ever
    changes, this should sort by an explicit timestamp first."""
    by_requirement: dict[str, Finding] = {}
    for finding in store.findings.list_by_project(project_id):
        if finding.requirement_id:
            by_requirement[finding.requirement_id] = finding
    return by_requirement


def apply_semantic_memory(store: Store, world_model: WorldModel) -> int:
    """Marks Unknowns resolved when a prior run already produced a Finding
    for the same requirement. Returns how many were resolved this way.
    Mutates world_model.unknowns in place."""
    prior = prior_findings_by_requirement(store, world_model.project_id)
    resolved_count = 0
    for unknown in world_model.unknowns:
        if unknown.resolved or not unknown.requirement_id:
            continue
        finding = prior.get(unknown.requirement_id)
        if finding is None:
            continue
        unknown.resolved = True
        unknown.rationale += (
            f" [Resolved from memory: already confirmed as a {finding.category.value} "
            f"in a prior run (finding {finding.id}, confidence {finding.confidence}).]"
        )
        resolved_count += 1
    return resolved_count
