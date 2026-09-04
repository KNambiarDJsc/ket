"""VeriForge Dashboard (Phase 20): a real web surface over the exact same
SQLite Store every other phase already persists to — job history,
requirements, findings, the Phase 18 Knowledge Graph, and a way to launch
a new verification run — plus a natural-language query bar
(`dashboard/nl_query.py`). This is "the one genuinely separate product
surface" the roadmap named: its own stack (FastAPI + vanilla JS, no build
step), never a second source of truth.

`POST /api/verify` runs a real job synchronously in the request handler —
deliberately, not queued to a background worker: building a job queue
would be real, separate infrastructure this vertical slice doesn't need
to prove itself, the same "don't build past what's demonstrated"
discipline as every earlier phase's own deferrals. A long-running
verification (real browser exploration, a GitHub clone) blocks that one
request until it finishes; a future phase queuing this properly is real,
separate work, not a gap in what's built here.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from veriforge.dashboard.nl_query import answer_question
from veriforge.events.bus import EventBus
from veriforge.knowledge_graph.graph import build_knowledge_graph
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.run_verify import GitHubCloneError, VerifyParams, run_verify
from veriforge.storage.repository import Store

_STATIC_DIR = Path(__file__).resolve().parent / "static"


class JobSummaryOut(BaseModel):
    id: str
    project_id: str
    project_name: str
    state: str
    verdict: str | None
    finding_count: int
    created_at: str
    repo_path: str | None
    base_url: str | None


class AskRequest(BaseModel):
    question: str


class AskResponseOut(BaseModel):
    answer: str
    matched_job_ids: list[str]


class VerifyRequestIn(BaseModel):
    repo: str | None = None
    subdir: str | None = None
    url: str | None = None
    requirements: str | None = None
    db_path: str | None = None


def create_app(*, store: Store, bus: EventBus, llm: LLMProvider, workdir: str) -> FastAPI:
    app = FastAPI(title="VeriForge Dashboard")

    @app.get("/api/jobs")
    def list_jobs() -> list[JobSummaryOut]:
        jobs = sorted(store.jobs.list_all(), key=lambda j: j.created_at, reverse=True)
        projects_by_id = {p.id: p for p in store.projects.list_all()}
        out: list[JobSummaryOut] = []
        for job in jobs:
            findings = store.findings.list_by_job(job.id)
            test_runs = store.test_runs.list_by_job(job.id)
            verdict = test_runs[-1].verdict.value if test_runs and test_runs[-1].verdict else None
            project = projects_by_id.get(job.project_id)
            out.append(JobSummaryOut(
                id=job.id, project_id=job.project_id,
                project_name=project.name if project else job.project_id,
                state=job.state.value, verdict=verdict, finding_count=len(findings),
                created_at=job.created_at.isoformat(), repo_path=job.repo_path, base_url=job.base_url,
            ))
        return out

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str) -> dict:
        job = store.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return {
            "job": job.model_dump(mode="json"),
            "requirements": [r.model_dump(mode="json") for r in store.requirements.list_by_job(job_id)],
            "findings": [f.model_dump(mode="json") for f in store.findings.list_by_job(job_id)],
            "test_runs": [t.model_dump(mode="json") for t in store.test_runs.list_by_job(job_id)],
            "artifacts": [a.model_dump(mode="json") for a in store.artifacts.list_by_job(job_id)],
        }

    @app.get("/api/jobs/{job_id}/graph")
    def job_graph(job_id: str) -> dict:
        job = store.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        world_models = store.world_models.list_by_job(job_id)
        if not world_models:
            raise HTTPException(404, "no world model recorded for this job")

        graph = build_knowledge_graph(
            world_models[0],
            findings=store.findings.list_by_job(job_id),
            evidence=store.evidence.list_by_job(job_id),
            tests=store.tests.list_by_job(job_id),
            experiments=store.experiments.list_by_job(job_id),
        )
        return {
            "nodes": [{"id": n.id, "kind": n.kind.value, "label": n.label} for n in graph.nodes],
            "edges": [{"source": e.source_id, "target": e.target_id, "kind": e.kind.value} for e in graph.edges],
        }

    @app.post("/api/ask")
    def ask(request: AskRequest) -> AskResponseOut:
        result = answer_question(store, llm, request.question)
        return AskResponseOut(answer=result.answer, matched_job_ids=result.matched_job_ids)

    @app.post("/api/verify")
    def trigger_verify(request: VerifyRequestIn) -> dict:
        params = VerifyParams(
            repo=request.repo, subdir=request.subdir, url=request.url,
            requirements=request.requirements, db_path=request.db_path, workdir=workdir,
        )
        try:
            outcome = run_verify(params, store=store, bus=bus, llm=llm)
        except GitHubCloneError as exc:
            raise HTTPException(400, f"failed to clone --repo: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "job_id": outcome.job.id,
            "cloned_note": outcome.cloned_note,
            "verdict": outcome.summary.verdict,
            "finding_count": outcome.summary.finding_count,
            "top_hypothesis": outcome.summary.top_hypothesis,
            "warnings": outcome.warnings,
        }

    # Routes above must be registered before this catch-all mount, or it
    # would shadow every /api/* route declared after it.
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
    return app
