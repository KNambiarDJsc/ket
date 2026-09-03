from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from veriforge.config import load_dotenv_if_present
from veriforge.domain.models import Job, Project
from veriforge.events.bus import EventBus
from veriforge.llm.ollama_provider import DEFAULT_MODEL, OllamaProvider
from veriforge.llm.openai_compatible_provider import OpenAICompatibleProvider
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.job_runner import JobRunner
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


@app.callback()
def _callback() -> None:
    """VeriForge — Autonomous Software Verification & Testing OS."""
    # Present even though empty: forces Typer to keep `verify` as an explicit
    # subcommand instead of collapsing the single-command app into the
    # top-level invocation (Click/Typer merge a lone @app.command() away).


@app.command()
def verify(
    repo: Optional[str] = typer.Option(None, "--repo", help="Path to the repository under test"),
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

    # Phase 8: reuse the same Project (and thus project_id) across runs when
    # --repo matches one seen before, so cross-run memory has an identity to
    # attach to. Without this, every invocation got a fresh project_id and
    # nothing could ever be remembered.
    project = None
    if repo:
        project = next((p for p in store.projects.list_all() if p.repo_path == repo), None)
    if project is None:
        project = Project(name=Path(repo).name if repo else "veriforge-project", repo_path=repo, base_url=url)
        store.projects.save(project, project_id=project.id)

    job = Job(
        project_id=project.id,
        repo_path=repo,
        base_url=url,
        requirements_path=requirements,
        db_path=db_path,
        model_name=llm.model_name,
    )

    artifacts_dir = Path(workdir) / ".veriforge" / "artifacts"
    runner = JobRunner(store, bus, llm, artifacts_dir, write_regressions=write_regressions)

    console.print(f"[bold]Starting job {job.id}[/bold] (project {project.id})")
    try:
        summary = runner.run(job)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Job failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        store.close()

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


if __name__ == "__main__":
    app()
