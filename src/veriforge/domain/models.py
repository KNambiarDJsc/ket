"""Core domain models for VeriForge.

These are plain Pydantic models — the persistence layer (storage/schema.py)
maps them to SQL rows. Keeping domain models free of ORM concerns means the
orchestrator and future agents never depend on SQLAlchemy directly.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from veriforge.domain.enums import (
    EventType,
    FailureCategory,
    JobState,
    RequirementKind,
    RiskLevel,
    TestStatus,
    Verdict,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def stable_id(prefix: str, *parts: str) -> str:
    """Deterministic id derived from `parts` rather than random -- so the
    "same" logical thing (e.g. a requirement's text within a project) gets
    the same id every time it's parsed, across separate runs. Without this,
    cross-run memory (Phase 8) can never match anything: a fresh random id
    every parse means a later run's Requirement never lines up with an
    earlier run's Finding for "the same" requirement."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("proj"))
    name: str
    repo_path: str | None = None
    base_url: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Requirement(BaseModel):
    id: str = Field(default_factory=lambda: new_id("req"))
    project_id: str
    source_text: str
    kind: RequirementKind = RequirementKind.UNSPECIFIED
    # Structured fields populated once §5-style invariant extraction lands
    # (phase 3+). Left generic/opt-in so phase 1 can persist raw requirements
    # without pretending to understand them yet.
    structured: dict[str, Any] | None = None
    critical: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Feature(BaseModel):
    id: str = Field(default_factory=lambda: new_id("feat"))
    project_id: str
    name: str
    description: str = ""
    requirement_ids: list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wf"))
    project_id: str
    name: str
    steps: list[str] = Field(default_factory=list)


class WorldModelState(BaseModel):
    """A single observed or hypothesized state of the system under test."""

    id: str = Field(default_factory=lambda: new_id("state"))
    project_id: str
    description: str
    data: dict[str, Any] = Field(default_factory=dict)


class Unknown(BaseModel):
    id: str = Field(default_factory=lambda: new_id("unk"))
    project_id: str
    question: str
    rationale: str = ""
    resolved: bool = False
    requirement_id: str | None = None  # set when this Unknown traces back to a specific Requirement


class ApiEndpoint(BaseModel):
    """An HTTP endpoint discovered by static analysis (AST-based, not LLM
    guessed — see cartography/python_ast.py). `mentions_role_check` is a raw
    fact (did the handler source reference an auth-looking identifier?), not
    a verdict — deciding whether authorization is actually enforced is the
    Oracle's job (Phase 6), once there's an Executor to actually call it.
    """

    id: str = Field(default_factory=lambda: new_id("api"))
    project_id: str
    method: str
    path: str
    source_file: str
    source_line: int
    mentions_role_check: bool = False


class WorldModel(BaseModel):
    """Aggregate root the rest of the system reads/writes through.

    Phase 1 populates project/requirements/repo_facts/unknowns from real
    (non-LLM-hallucinated) sources: the requirements parser and the
    filesystem cartographer. Phase 3 adds api_endpoints (AST-based route
    extraction) and structures each Requirement's `.structured` field via
    requirements/invariants.py. Workflows/states get populated once the
    Explorer (Phase 4) exists.
    """

    id: str = Field(default_factory=lambda: new_id("wm"))
    project_id: str
    requirements: list[Requirement] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    states: list[WorldModelState] = Field(default_factory=list)
    unknowns: list[Unknown] = Field(default_factory=list)
    repo_facts: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exp"))
    project_id: str
    hypothesis: str
    requirement_id: str | None = None
    score: float = 0.0
    rationale: str = ""


class Test(BaseModel):
    __test__ = False  # tell pytest this isn't a test class despite the name

    id: str = Field(default_factory=lambda: new_id("test"))
    project_id: str
    experiment_id: str | None = None
    name: str
    status: TestStatus = TestStatus.HYPOTHESIS


class TestRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    test_id: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    verdict: Verdict | None = None


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obs"))
    test_run_id: str
    tool: str
    action: str
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ev"))
    finding_id: str | None = None
    kind: str  # e.g. screenshot, network_capture, log, db_snapshot
    uri: str


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("find"))
    project_id: str
    test_run_id: str | None = None
    category: FailureCategory = FailureCategory.UNKNOWN
    summary: str
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    root_cause: str | None = None  # Phase 7 Investigator: static+dynamic evidence tied together
    reproduced: bool | None = None  # Phase 7 Reproducer: None = not attempted
    requirement_id: str | None = None  # Phase 8 semantic memory: lets a later run recognize "already confirmed"


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    job_id: str
    kind: str  # e.g. "world-model.json", "run-summary.json"
    path: str
    created_at: datetime = Field(default_factory=utcnow)


class Learning(BaseModel):
    id: str = Field(default_factory=lambda: new_id("learn"))
    project_id: str
    change: str
    reason: str
    prediction: str
    baseline_metric: float | None = None
    target_metric: float | None = None
    measured_metric: float | None = None
    kept: bool | None = None


class Strategy(BaseModel):
    id: str = Field(default_factory=lambda: new_id("strat"))
    project_id: str
    name: str
    version: int = 1
    weights: dict[str, float] = Field(default_factory=dict)


class Event(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    job_id: str
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("arun"))
    job_id: str
    agent_name: str
    input_summary: str = ""
    output_summary: str = ""
    tool_calls: int = 0
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class LoopState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("loop"))
    job_id: str
    iteration: int = 0
    max_iterations: int | None = None
    tokens_used: int = 0
    max_tokens: int | None = None
    stop_reason: str | None = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    project_id: str
    state: JobState = JobState.JOB_CREATED
    repo_path: str | None = None
    base_url: str | None = None
    requirements_path: str | None = None
    db_path: str | None = None  # Phase 11: SQLite file for direct DB-state verification
    model_name: str = "llama3.2:3b"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    error: str | None = None
