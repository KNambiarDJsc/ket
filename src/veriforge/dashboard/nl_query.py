"""Natural-language command bar (Phase 20): answers a free-text question
about this project's own job/finding history by giving the LLM a compact,
real summary of that data (never raw SQL, never arbitrary code execution)
and asking it to answer strictly from that summary -- the same context-
budgeting discipline as `context.compiler.ContextCompiler`, applied to a
chat-style query instead of a Test-Scientist prompt.

Deliberately read-only and scoped to *existing* data. Translating a
free-text request into a NEW job (which repo to clone, which URL to hit)
would mean an LLM deciding what to execute against a live system from a
prompt it might misread -- exactly the kind of unreviewed, LLM-initiated
side effect this project's harness/permission model exists to prevent
everywhere else. Launching a job stays a separate, explicit, structured
action (the dashboard's own `/api/verify`), never inferred from `ask`.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.llm.provider import LLMProvider, LLMUnavailableError
from veriforge.storage.repository import Store

_MAX_JOBS_IN_CONTEXT = 30


@dataclass
class AskResult:
    answer: str
    matched_job_ids: list[str]


def _build_context(store: Store) -> tuple[str, list[str]]:
    jobs = sorted(store.jobs.list_all(), key=lambda j: j.created_at, reverse=True)[:_MAX_JOBS_IN_CONTEXT]
    projects_by_id = {p.id: p for p in store.projects.list_all()}
    lines: list[str] = []
    job_ids: list[str] = []

    for job in jobs:
        findings = store.findings.list_by_job(job.id)
        project = projects_by_id.get(job.project_id)
        test_runs = store.test_runs.list_by_job(job.id)
        verdict = test_runs[-1].verdict.value if test_runs and test_runs[-1].verdict else "none"
        finding_summaries = "; ".join(f"{f.category.value}: {f.summary[:80]}" for f in findings) or "no findings"
        lines.append(
            f"- job {job.id} (project {project.name if project else job.project_id}): "
            f"state={job.state.value} verdict={verdict} findings=[{finding_summaries}]"
        )
        job_ids.append(job.id)

    return "\n".join(lines), job_ids


def answer_question(store: Store, llm: LLMProvider, question: str) -> AskResult:
    context, job_ids = _build_context(store)
    if not context:
        return AskResult("No jobs have been run yet against this workdir.", [])

    prompt = (
        "You are answering a question about VeriForge job history using ONLY the data below. "
        "If the data doesn't answer the question, say so plainly -- never guess.\n\n"
        f"Job history:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    )
    try:
        answer = llm.generate(prompt)
    except LLMUnavailableError:
        return AskResult(
            "No LLM is configured or reachable, so this can't be answered in natural "
            f"language. Here is the raw job history instead:\n{context}",
            job_ids,
        )
    return AskResult(answer.strip(), job_ids)
