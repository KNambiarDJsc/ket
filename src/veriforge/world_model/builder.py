"""Assembles a WorldModel from requirements + cartographer facts.

This is where requirement structuring (requirements/invariants.py) meets
repository facts (cartography/cartographer.py): an AUTHORIZATION/NEGATIVE
requirement like "Members cannot delete projects" gets matched, by simple
action/object keyword overlap, against a discovered endpoint like
`DELETE /projects/<id>`. The match — and whether that endpoint's handler
source even mentions a role/permission check — becomes part of the Unknown's
rationale. This is still a fact/observation, not a verdict: nothing here has
actually called the endpoint. Confirming the bug is the Oracle's job once
Phase 6 exists.
"""
from __future__ import annotations

from dataclasses import asdict

from veriforge.domain.models import (
    ApiEndpoint,
    Requirement,
    Unknown,
    Workflow,
    WorldModel,
    WorldModelState,
)
from veriforge.explorer.browser import ExplorationResult
from veriforge.requirements.invariants import apply_invariants

ACTION_TO_METHOD = {
    "delete": "DELETE",
    "create": "POST",
    "edit": "PUT",
    "view": "GET",
}

def object_keyword(object_text: str) -> str | None:
    words = [w.strip(".,;:") for w in object_text.lower().split()]
    significant = [w for w in words if len(w) > 3]
    return significant[-1] if significant else None


def match_endpoint_for_requirement(requirement: Requirement, endpoints: list[ApiEndpoint]) -> ApiEndpoint | None:
    structured = requirement.structured
    if not structured or "action" not in structured or "object" not in structured:
        return None
    method = ACTION_TO_METHOD.get(structured["action"])
    keyword = object_keyword(structured["object"])
    if not method or not keyword:
        return None
    for ep in endpoints:
        if ep.method == method and keyword in ep.path.lower():
            return ep
    # Fall back to a bare noun match (e.g. "projects" in both requirement and path)
    # when the more specific keyword above didn't match any known endpoint.
    words = {w.strip(".,;:") for w in structured["object"].lower().split()}
    for ep in endpoints:
        if ep.method == method and any(w in ep.path.lower() for w in words if len(w) > 3):
            return ep
    return None


def build_unknowns(requirements: list[Requirement], endpoints: list[ApiEndpoint]) -> list[Unknown]:
    unknowns: list[Unknown] = []
    for req in requirements:
        if not req.critical:
            continue
        endpoint = match_endpoint_for_requirement(req, endpoints)
        if endpoint is not None and not endpoint.mentions_role_check:
            rationale = (
                f"Matched to {endpoint.method} {endpoint.path} ({endpoint.source_file}:{endpoint.source_line}); "
                "handler source has no role/permission-check identifier. Not yet executed — needs "
                "the Executor/Oracle (Phase 6) to confirm whether this is actually enforced."
            )
        elif endpoint is not None:
            rationale = (
                f"Matched to {endpoint.method} {endpoint.path} ({endpoint.source_file}:{endpoint.source_line}); "
                "handler source does reference a role/permission-looking identifier, but enforcement "
                "is unverified until Phase 6 (Oracle)."
            )
        else:
            rationale = (
                "No matching endpoint found by static analysis for this requirement's action/object; "
                "requirement coverage unknown."
            )
        unknowns.append(
            Unknown(
                project_id=req.project_id,
                question=f"Has this been verified end-to-end: '{req.source_text}'?",
                rationale=rationale,
                requirement_id=req.id,
            )
        )
    return unknowns


def build_exploration_unknowns(project_id: str, exploration: ExplorationResult) -> list[Unknown]:
    """Each skipped-destructive element becomes a candidate for a future,
    deliberate experiment (Phase 5's Test Scientist) rather than something the
    bounded auto-explorer decided on its own to click."""
    return [
        Unknown(
            project_id=project_id,
            question=f"What happens when a user activates: {description.split(' (looks destructive')[0]}?",
            rationale=f"Discovered by browser exploration but not auto-clicked: {description}",
        )
        for description in exploration.skipped_destructive
    ]


def build_world_model(
    project_id: str,
    requirements: list[Requirement],
    repo_facts: dict,
    exploration: ExplorationResult | None = None,
) -> WorldModel:
    apply_invariants(requirements)  # populates each Requirement.structured in place

    raw_endpoints = repo_facts.get("endpoints", []) if repo_facts else []
    endpoints = [
        ApiEndpoint(
            project_id=project_id,
            method=e["method"],
            path=e["path"],
            source_file=e["source_file"],
            source_line=e["source_line"],
            mentions_role_check=e["mentions_role_check"],
        )
        for e in raw_endpoints
    ]

    unknowns = build_unknowns(requirements, endpoints)

    states: list[WorldModelState] = []
    workflows: list[Workflow] = []
    if exploration is not None:
        states = [
            WorldModelState(
                project_id=project_id,
                description=f'Page observed: {page.url} ("{page.title}")',
                data={"elements": [asdict(e) for e in page.elements], "screenshot_path": page.screenshot_path},
            )
            for page in exploration.pages
        ]
        if exploration.workflow_steps:
            workflows = [
                Workflow(project_id=project_id, name="bounded auto-exploration", steps=exploration.workflow_steps)
            ]
        unknowns += build_exploration_unknowns(project_id, exploration)

    return WorldModel(
        project_id=project_id,
        requirements=requirements,
        api_endpoints=endpoints,
        unknowns=unknowns,
        states=states,
        workflows=workflows,
        repo_facts=repo_facts,
    )
