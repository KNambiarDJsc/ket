"""Shared "run a verify job" core (Phase 20): the exact source-resolution,
LLM-provider, and Project-reuse logic `cli/main.py`'s `verify` command
used to inline, extracted so the Dashboard's `POST /api/verify` can launch
a real job without duplicating it. Console/Typer-free on purpose -- a
caller decides how to report progress or errors, not this function.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veriforge.domain.models import Job, Project
from veriforge.events.bus import EventBus
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.job_runner import JobRunner, RunSummary
from veriforge.source.github import GitHubCloneError, display_name, is_github_url
from veriforge.source.resolve import resolve_source_spec
from veriforge.storage.repository import Store


@dataclass
class VerifyParams:
    repo: str | None = None
    subdir: str | None = None
    url: str | None = None
    requirements: str | None = None
    db_path: str | None = None
    write_regressions: bool = False
    workdir: str = "."


@dataclass
class VerifyOutcome:
    summary: RunSummary
    job: Job
    project: Project
    cloned_note: str | None  # a human-readable "Cloned X -> Y" note, or None if nothing was cloned
    # Phase 20 UX fix: --repo alone (even a real GitHub URL) can only ever
    # produce static analysis -- there is no requirement to check and no live
    # target to check it against, so no experiment can ever run. Every prior
    # phase already reports this honestly buried in hypotheses.json's
    # execution_note, but a job still completes looking identical to a real
    # PASS/FAIL run (verdict=null, 0 findings, state=COMPLETED) with nothing
    # surfaced to say why -- see docs/PHASES.md's 2026-09-04 note. Callers
    # (CLI, Dashboard) must show these prominently, not bury them.
    warnings: list[str]


def run_verify(params: VerifyParams, *, store: Store, bus: EventBus, llm: LLMProvider) -> VerifyOutcome:
    if not any([params.repo, params.url, params.requirements]):
        raise ValueError("At least one of repo, url, requirements is required.")

    # Phase 17: --repo may be a GitHub URL instead of a local path -- clone
    # it into an isolated per-run workspace first. Every downstream module
    # keeps working against a plain local directory, unaware anything was
    # cloned. May raise GitHubCloneError -- the caller decides how to report it.
    resolved_repo_path = params.repo
    cloned_root: str | None = None
    cloned_note: str | None = None
    requirements = params.requirements
    db_path = params.db_path

    if params.repo and is_github_url(params.repo):
        resolved = resolve_source_spec(params.repo, Path(params.workdir))
        cloned_root = resolved.local_path
        resolved_repo_path = str(Path(cloned_root) / params.subdir) if params.subdir else cloned_root
        commit_note = f" @ {resolved.commit_sha[:12]}" if resolved.commit_sha else ""
        cloned_note = f"Cloned {params.repo}{commit_note} -> {resolved_repo_path}"
    elif params.subdir and params.repo:
        resolved_repo_path = str(Path(params.repo) / params.subdir)

    # A relative requirements/db_path is given relative to the cloned repo's
    # root (not --subdir), only when --repo was actually cloned; a plain
    # local repo keeps its prior, unchanged (cwd-relative) behavior.
    if cloned_root:
        if requirements and not Path(requirements).is_absolute():
            requirements = str(Path(cloned_root) / requirements)
        if db_path and not Path(db_path).is_absolute():
            db_path = str(Path(cloned_root) / db_path)

    # Phase 8: reuse the same Project across runs when --repo matches one
    # seen before, matched on the *original* spec (a GitHub URL included) --
    # Phase 17's per-run clone gives each job its own isolated directory, so
    # matching on the resolved path would never find a prior run's Project.
    project = None
    if params.repo:
        project = next((p for p in store.projects.list_all() if p.repo_path == params.repo), None)
    if project is None:
        default_name = (
            display_name(params.repo) if params.repo and is_github_url(params.repo)
            else (Path(params.repo).name if params.repo else "veriforge-project")
        )
        project = Project(name=default_name, repo_path=params.repo, base_url=params.url)
        store.projects.save(project, project_id=project.id)

    job = Job(
        project_id=project.id,
        repo_path=resolved_repo_path,
        base_url=params.url,
        requirements_path=requirements,
        db_path=db_path,
        model_name=llm.model_name,
    )

    artifacts_dir = Path(params.workdir) / ".veriforge" / "artifacts"
    runner = JobRunner(store, bus, llm, artifacts_dir, write_regressions=params.write_regressions)
    summary = runner.run(job)

    warnings: list[str] = []
    if not requirements and not params.url:
        warnings.append(
            "No --requirements and no --url were given: only a static repo scan "
            "(and an LLM summary, if a provider is configured) was performed. No "
            "requirement was checked and no experiment could be executed -- this "
            "run cannot confirm or rule out any bug."
        )
    elif not params.url:
        warnings.append(
            "No --url was given: requirements were parsed but there was no live "
            "app to execute anything against -- every hypothesis stayed queued, "
            "unexecuted."
        )
    elif not requirements:
        warnings.append(
            "No --requirements were given: the app was reachable/explored but "
            "there is nothing to check it against, so no experiment could be "
            "ranked or executed."
        )

    return VerifyOutcome(summary=summary, job=job, project=project, cloned_note=cloned_note, warnings=warnings)


__all__ = ["VerifyParams", "VerifyOutcome", "run_verify", "GitHubCloneError"]
