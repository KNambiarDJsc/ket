"""Semantic memory: facts already established about this project from prior
runs — specifically, "has this requirement already been confirmed violated
(or verified okay) by a past run's Finding?" so a later run doesn't re-flag
an already-answered question as a fresh Unknown.

Deliberately exact-key lookup (by requirement_id), not embedding similarity
search — nomic-embed-text is pulled locally and reserved for when the system
actually needs "find findings *similar* to this one"; that's not this.

Phase 13 closes a gap Phase 8 documented rather than guessed at: "once
memory resolves an Unknown, the current run's Test Scientist skips it
entirely... [so] if a bug were later fixed, nothing here would notice."
When `current_job` is given and both it and the Finding's originating job
have a resolvable git commit (`regression/change_impact.py`), a prior
Finding only keeps resolving its Unknown if the code behind it hasn't
changed since; otherwise the Unknown is left open for re-verification,
with its rationale explaining why. Without `current_job` (or without git),
this degrades to Phase 8's original unconditional-resolve behavior.
"""
from __future__ import annotations

from veriforge.domain.models import Finding, Job, WorldModel
from veriforge.regression.change_impact import changed_files_since
from veriforge.storage.repository import Store
from veriforge.world_model.builder import match_endpoint_for_requirement


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


def apply_semantic_memory(store: Store, world_model: WorldModel, *, current_job: Job | None = None) -> int:
    """Marks Unknowns resolved when a prior run already produced a Finding
    for the same requirement -- unless (Phase 13) the code behind that
    Finding has since changed, in which case the Unknown is left open for
    re-verification instead. Returns how many were resolved (not reopened)
    this way. Mutates world_model.unknowns in place."""
    prior = prior_findings_by_requirement(store, world_model.project_id)
    requirements_by_id = {r.id: r for r in world_model.requirements}
    diff_cache: dict[str, set[str] | None] = {}

    def changed_since(commit: str) -> set[str] | None:
        if commit not in diff_cache:
            diff_cache[commit] = changed_files_since(current_job.repo_path, commit)
        return diff_cache[commit]

    resolved_count = 0
    for unknown in world_model.unknowns:
        if unknown.resolved or not unknown.requirement_id:
            continue
        finding = prior.get(unknown.requirement_id)
        if finding is None:
            continue

        if current_job is not None and current_job.repo_path and current_job.repo_commit and finding.job_id:
            prior_job = store.jobs.get(finding.job_id)
            if prior_job and prior_job.repo_commit and prior_job.repo_commit != current_job.repo_commit:
                requirement = requirements_by_id.get(unknown.requirement_id)
                endpoint = match_endpoint_for_requirement(requirement, world_model.api_endpoints) if requirement else None
                changed = changed_since(prior_job.repo_commit)
                if endpoint is not None and changed is not None and endpoint.source_file in changed:
                    unknown.rationale += (
                        f" [Previously confirmed in finding {finding.id} at commit {prior_job.repo_commit[:8]}, "
                        f"but {endpoint.source_file} has changed since (now at {current_job.repo_commit[:8]}) "
                        "-- re-verifying rather than trusting stale memory (Phase 13).]"
                    )
                    continue

        unknown.resolved = True
        unknown.rationale += (
            f" [Resolved from memory: already confirmed as a {finding.category.value} "
            f"in a prior run (finding {finding.id}, confidence {finding.confidence}).]"
        )
        resolved_count += 1
    return resolved_count
