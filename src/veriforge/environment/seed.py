"""Seed Data/Users (Phase 14 Environment Engineering): populates a fresh
environment with known actors and resources via the application's own
API before tests run.

Every Executor since Phase 6 has created its own throwaway resource
per-experiment and discarded it afterward -- correct for "does this one
check pass," but Advanced testing areas (Phase 15's concurrency/security
engine especially) need real, *pre-existing*, multi-actor state to act on:
"can actor B see/modify a resource actor A already owns" has no answer if
nothing exists yet when the question is asked. This is the deterministic,
API-driven mechanism for creating that starting state -- never inserted
directly into a database, since seeding through the real API is itself a
first exercise of that API's creation path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from veriforge.harness.executor import ToolExecutor


@dataclass
class SeedActor:
    name: str
    role_header: str


@dataclass
class SeedResource:
    creation_path: str
    actor: str
    count: int = 1


@dataclass
class SeedSpec:
    actors: list[SeedActor] = field(default_factory=list)
    resources: list[SeedResource] = field(default_factory=list)


@dataclass
class SeededResource:
    body: dict
    actor: str
    creation_path: str


@dataclass
class SeedResult:
    created: list[SeededResource]


def seed_environment(base_url: str, spec: SeedSpec, tool_executor: ToolExecutor) -> SeedResult:
    actors_by_name = {actor.name: actor for actor in spec.actors}
    base = base_url.rstrip("/")
    created: list[SeededResource] = []

    for resource_spec in spec.resources:
        actor = actors_by_name.get(resource_spec.actor)
        headers = {"X-Role": actor.role_header} if actor is not None else None
        for _ in range(resource_spec.count):
            response = tool_executor.call("api.post", url=base + resource_spec.creation_path, headers=headers)
            try:
                body = response.json()
            except ValueError:
                body = {}
            created.append(
                SeededResource(body=body, actor=resource_spec.actor, creation_path=resource_spec.creation_path)
            )

    return SeedResult(created=created)
