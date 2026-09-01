"""Procedural memory: how to test this application -- a versioned, persisted
`Strategy` (the Test Scientist's scoring weights). A new project gets the
same DEFAULT_WEIGHTS the Strategist would use anyway; the point isn't a
different default, it's that this project's active weights now persist and
are addressable, so a future evaluated change (Phase 17's Evaluation Lab)
has something concrete to version and revert.
"""
from __future__ import annotations

from veriforge.domain.models import Strategy
from veriforge.storage.repository import Store
from veriforge.strategist.scientist import DEFAULT_WEIGHTS


def get_active_strategy(store: Store, project_id: str) -> Strategy:
    """Returns this project's highest-version Strategy, creating and
    persisting a default v1 the first time a project is seen."""
    strategies = store.strategies.list_by_project(project_id)
    if not strategies:
        strategy = Strategy(project_id=project_id, name="default", version=1, weights=dict(DEFAULT_WEIGHTS))
        store.strategies.save(strategy, project_id=project_id)
        return strategy
    return max(strategies, key=lambda s: s.version)
