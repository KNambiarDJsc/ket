"""Episodic memory: what happened during past runs of this project.

Not a separate store — these are just query patterns over the existing
job/finding tables, scoped by project_id. No new infrastructure.
"""
from __future__ import annotations

from veriforge.domain.models import Finding, Job
from veriforge.storage.repository import Store


def get_run_history(store: Store, project_id: str) -> list[Job]:
    """Past jobs for this project, oldest first."""
    return sorted(store.jobs.list_by_project(project_id), key=lambda j: j.created_at)


def get_past_findings(store: Store, project_id: str) -> list[Finding]:
    """Every Finding ever recorded for this project, across all runs."""
    return store.findings.list_by_project(project_id)
