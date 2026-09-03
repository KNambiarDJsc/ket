from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from veriforge.ci.pr_reporter import InvalidPrTargetError, format_pr_comment, parse_pr_target, post_pr_comment
from veriforge.config import load_dotenv_if_present
from veriforge.events.bus import EventBus
from veriforge.llm.ollama_provider import DEFAULT_MODEL, OllamaProvider
from veriforge.llm.openai_compatible_provider import OpenAICompatibleProvider
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.run_verify import GitHubCloneError, VerifyParams, run_verify
from veriforge.storage.db import get_engine, get_session
from veriforge.storage.repository import Store
from veriforge.storage.schema import create_all

load_dotenv_if_present()  # populates os.environ from ./.env before any option default reads it

app = typer.Typer(help="VeriForge — Autonomous Software Verification & Testing OS")
console = Console()


def _build_llm_provider(provider: str, model: str | None) -> LLMProvider:
    if provider == "openai":
        return OpenAICompatibleProvider(model=model)
    return OllamaProvider(model=model or DEFAULT_MODEL)


def _post_pr_comment_or_warn(target: str, *, job_id: str, repo_display: str, verdict, findings) -> None:
    token = os.environ.get("VERIFORGE_GITHUB_TOKEN")
    if not token:
        console.print("[yellow]--post-pr given but VERIFORGE_GITHUB_TOKEN is not set -- skipping.[/yellow]")
        return
    try:
        owner, repo_name, pr_number = parse_pr_target(target)
    except InvalidPrTargetError as exc:
        console.print(f"[red]--post-pr:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    body = format_pr_comment(job_id=job_id, repo_display=repo_display, verdict=verdict, findings=findings)
    try:
        post_pr_comment(owner=owner, repo=repo_name, pr_number=pr_number, body=body, token=token)
    except Exception as exc:  # noqa: BLE001 - a failed PR post shouldn't mask a successful job run
        console.print(f"[red]Failed to post PR comment:[/red] {exc}")
        return
    console.print(f"[green]Posted result to {target}[/green]")


@app.callback()
def _callback() -> None:
    """VeriForge — Autonomous Software Verification & Testing OS."""
    # Present even though empty: forces Typer to keep `verify` as an explicit
    # subcommand instead of collapsing the single-command app into the
    # top-level invocation (Click/Typer merge a lone @app.command() away).


@app.command()
def verify(
    repo: Optional[str] = typer.Option(
        None, "--repo", help="Path to the repository under test, or a GitHub URL to clone (Phase 17)"
    ),
    subdir: Optional[str] = typer.Option(
        None, "--subdir",
        help="Path relative to --repo's root to actually analyze (useful when --repo is a monorepo/GitHub clone)",
    ),
    url: Optional[str] = typer.Option(None, "--url", help="Base URL of the running application"),
    requirements: Optional[str] = typer.Option(
        None, "--requirements", help="Path to a requirements markdown file"
    ),
    db_path: Optional[str] = typer.Option(
        None, "--db-path", help="Path to a SQLite database file, for direct DB-state verification (Phase 11)"
    ),
    write_regressions: bool = typer.Option(
        False, "--write-regressions",
        help="Write a permanent regression test into --repo for every BUG_VERIFIED finding (Phase 13). Off by default.",
    ),
    llm_provider: str = typer.Option(
        None, "--llm-provider",
        help=(
            "Which LLM backend to use: 'ollama' (default, local) or 'openai' "
            "(any OpenAI-compatible /v1/chat/completions endpoint, e.g. an internal "
            "LiteLLM proxy — configure VERIFORGE_OPENAI_BASE_URL/VERIFORGE_OPENAI_API_KEY, "
            "in .env or the environment). Falls back to VERIFORGE_LLM_PROVIDER, then 'ollama'."
        ),
    ),
    model: Optional[str] = typer.Option(
        None, "--model",
        help="Model name for the selected provider (Ollama: must be `ollama pull`ed already). "
        "Falls back to VERIFORGE_LLM_MODEL, then the provider's own default.",
    ),
    workdir: str = typer.Option(".", "--workdir", help="Directory to store .veriforge/ state in"),
    post_pr: Optional[str] = typer.Option(
        None, "--post-pr",
        help="Post this run's result as a comment on a GitHub PR, e.g. 'owner/repo#123' "
        "(Phase 20). Requires VERIFORGE_GITHUB_TOKEN. Never posted unless explicitly given.",
    ),
):
    """Run the full Phase 0/1 job lifecycle against a repo/URL/requirements set."""
    if not any([repo, url, requirements]):
        console.print("[red]At least one of --repo, --url, --requirements is required.[/red]")
        raise typer.Exit(code=1)

    provider_name = llm_provider or os.environ.get("VERIFORGE_LLM_PROVIDER", "ollama")

    engine = get_engine(workdir)
    create_all(engine)
    session = get_session(workdir)
    store = Store(session)
    bus = EventBus(store)
    llm = _build_llm_provider(provider_name, model)

    if not llm.is_available():
        if provider_name == "openai":
            console.print(
                f"[yellow]Warning:[/yellow] OpenAI-compatible endpoint not reachable, or the "
                f"model '{llm.model_name}' rejected the request. Check VERIFORGE_OPENAI_BASE_URL "
                f"and VERIFORGE_OPENAI_API_KEY. Analysis will proceed without LLM summarization."
            )
        else:
            console.print(
                f"[yellow]Warning:[/yellow] Ollama not reachable at its configured host, "
                f"or model '{llm.model_name}' not pulled. Analysis will proceed without LLM summarization. "
                f"(Run `ollama pull {llm.model_name}` and ensure `ollama serve` is running.)"
            )

    params = VerifyParams(
        repo=repo, subdir=subdir, url=url, requirements=requirements, db_path=db_path,
        write_regressions=write_regressions, workdir=workdir,
    )
    console.print("[bold]Starting verification run...[/bold]")
    try:
        outcome = run_verify(params, store=store, bus=bus, llm=llm)
    except GitHubCloneError as exc:
        console.print(f"[red]Failed to clone --repo:[/red] {exc}")
        store.close()
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Job failed:[/red] {exc}")
        store.close()
        raise typer.Exit(code=1) from exc

    if outcome.cloned_note:
        console.print(f"[bold]{outcome.cloned_note}[/bold]")
    console.print(f"[bold]Job {outcome.job.id}[/bold] (project {outcome.project.id})")
    summary = outcome.summary
    findings_for_pr = store.findings.list_by_job(outcome.job.id)
    store.close()

    if post_pr:
        _post_pr_comment_or_warn(post_pr, job_id=outcome.job.id, repo_display=repo or "unknown", verdict=summary.verdict, findings=findings_for_pr)

    table = Table(title=f"VeriForge run summary — job {summary.job_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Final state", summary.final_state)
    table.add_row("Duration (s)", f"{summary.duration_seconds:.2f}")
    table.add_row("Requirements parsed", str(summary.requirement_count))
    table.add_row("Critical requirements", str(summary.critical_requirement_count))
    table.add_row("Unknowns identified", str(summary.unknown_count))
    table.add_row("Pages explored", str(summary.pages_explored))
    table.add_row("Hypotheses generated", str(summary.hypotheses_generated))
    if summary.top_hypothesis:
        table.add_row("Top-ranked hypothesis", summary.top_hypothesis)
    table.add_row("Tests executed", str(summary.test_count))
    if summary.verdict:
        style = "red" if summary.verdict == "FAIL" else "green" if summary.verdict == "PASS" else "yellow"
        table.add_row("Verdict", f"[{style}]{summary.verdict}[/{style}]")
    if summary.reproduced is not None:
        table.add_row("Reproduced", "yes" if summary.reproduced else "no (possibly flaky)")
    table.add_row("Findings", str(summary.finding_count))
    if summary.regression_test_path:
        table.add_row("Regression test written", summary.regression_test_path)
    table.add_row("Strategy version", str(summary.strategy_version))
    if summary.unknowns_resolved_from_memory:
        table.add_row("Resolved from memory", str(summary.unknowns_resolved_from_memory))
    if summary.learning_kept is not None:
        table.add_row("Strategy kept", "yes" if summary.learning_kept else "no (reverted)")
    table.add_row("Events recorded", str(summary.event_count))
    table.add_row("Tool calls used", str(summary.tool_calls_used))
    table.add_row("Artifacts written", str(len(summary.artifact_paths)))
    table.add_row("Next phase", summary.next_phase)
    console.print(table)

    console.print("\n[bold]Artifacts:[/bold]")
    for path in summary.artifact_paths:
        console.print(f"  {path}")


@app.command()
def dashboard(
    workdir: str = typer.Option(".", "--workdir", help="Directory whose .veriforge/ state to serve"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8420, "--port"),
    llm_provider: str = typer.Option(
        None, "--llm-provider", help="LLM backend for the 'ask' bar: 'ollama' (default) or 'openai'.",
    ),
    model: Optional[str] = typer.Option(None, "--model"),
):
    """Serve the VeriForge Dashboard (Phase 20) over the same .veriforge/
    state a `verify` run against this --workdir already writes to."""
    import uvicorn

    from veriforge.dashboard.api import create_app

    provider_name = llm_provider or os.environ.get("VERIFORGE_LLM_PROVIDER", "ollama")
    engine = get_engine(workdir)
    create_all(engine)
    session = get_session(workdir)
    store = Store(session)
    bus = EventBus(store)
    llm = _build_llm_provider(provider_name, model)

    dashboard_app = create_app(store=store, bus=bus, llm=llm, workdir=workdir)
    console.print(f"[bold]VeriForge Dashboard[/bold] on http://{host}:{port} (workdir: {workdir})")
    uvicorn.run(dashboard_app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
