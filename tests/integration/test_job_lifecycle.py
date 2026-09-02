"""End-to-end Phase 1 lifecycle: real requirements file, real repo scan, real
persisted job/events/artifacts, driven through JobRunner exactly as the CLI
does. Uses a fake LLM provider here for determinism/speed; test_ollama_provider.py
covers the real local-model path separately.
"""
from __future__ import annotations

from pathlib import Path

from veriforge.domain.enums import JobState
from veriforge.domain.models import Job
from veriforge.events.bus import EventBus
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.job_runner import JobRunner
from veriforge.storage.repository import Store

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


class FakeLLMProvider(LLMProvider):
    def __init__(self):
        self.calls: list[str] = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append(prompt)
        return "This looks like a small Python service."

    def is_available(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "fake-model"


def test_full_job_lifecycle_reaches_completed(store, tmp_path):
    bus = EventBus(store)
    llm = FakeLLMProvider()
    runner = JobRunner(store, bus, llm, artifacts_dir=tmp_path / "artifacts")

    job = Job(
        project_id="proj_1",
        repo_path=str(EXAMPLES_DIR / "example-app"),
        requirements_path=str(EXAMPLES_DIR / "requirements.md"),
    )

    summary = runner.run(job)

    assert job.state == JobState.COMPLETED
    assert summary.final_state == "COMPLETED"
    assert summary.requirement_count == 6
    assert summary.critical_requirement_count >= 2
    assert summary.test_count == 0  # honest: no Executor/Oracle yet
    assert summary.hypotheses_generated >= 1  # Test Scientist ranked real candidates
    assert summary.top_hypothesis is not None
    # requirements/init/analysis/world-model/context-bundle/skills-retrieved/
    # learning/hypotheses (run-summary.json is written after this list is
    # computed, since it can't include itself)
    assert len(summary.artifact_paths) == 8
    assert summary.strategy_version == 1
    assert summary.learning_kept is None  # insufficient prior runs to judge yet
    assert summary.tool_calls_used >= 2  # filesystem.scan_repository + llm.generate
    assert llm.calls, "expected the analysis step to call the LLM at least once"

    for path in summary.artifact_paths:
        assert Path(path).exists()

    # Phase 12: the real bundled skills/*/SKILL.md are discoverable and
    # actually retrieved for this job's real goal string -- not just
    # structurally wired but exercised end-to-end.
    import json as _json
    skills_artifact_path = next(p for p in summary.artifact_paths if p.endswith("skills-retrieved.json"))
    skills_retrieved = _json.loads(Path(skills_artifact_path).read_text(encoding="utf-8"))
    assert skills_retrieved["retrieved"], "expected at least one bundled Skill to match the real job goal"

    experiments = store.experiments.list_by_job(job.id)
    tests = store.tests.list_by_job(job.id)
    assert len(experiments) == summary.hypotheses_generated
    assert len(tests) == len(experiments)
    assert any(t.status.value == "PLANNED" for t in tests)
    # the intentional authorization bug (Phase 3's static finding) should rank
    # highly since it carries the real "no role check" signal
    assert "Members cannot delete projects" in experiments[0].hypothesis

    events = bus.history(job.id)
    transitions = [e.payload["to"] for e in events if e.type.value == "JOB_STATE_CHANGED"]
    assert transitions == [
        "REQUIREMENTS_RECEIVED",
        "JOB_INITIALIZED",
        "ANALYSIS_PENDING",
        "WORLD_MODEL_PENDING",
        "TESTING_PENDING",
        "COMPLETED",
    ]


def test_missing_repo_path_does_not_crash_analysis(store, tmp_path):
    bus = EventBus(store)
    llm = FakeLLMProvider()
    runner = JobRunner(store, bus, llm, artifacts_dir=tmp_path / "artifacts")

    job = Job(project_id="proj_1", requirements_path=str(EXAMPLES_DIR / "requirements.md"))
    summary = runner.run(job)

    assert summary.final_state == "COMPLETED"


def test_job_with_base_url_runs_browser_exploration(store, tmp_path, example_app_server):
    bus = EventBus(store)
    llm = FakeLLMProvider()
    runner = JobRunner(store, bus, llm, artifacts_dir=tmp_path / "artifacts")

    job = Job(
        project_id="proj_1",
        repo_path=str(EXAMPLES_DIR / "example-app"),
        requirements_path=str(EXAMPLES_DIR / "requirements.md"),
        base_url=f"{example_app_server}/ui",
    )

    summary = runner.run(job)

    assert summary.final_state == "COMPLETED"
    assert summary.pages_explored >= 1
    assert any(p.endswith("exploration.json") for p in summary.artifact_paths)

    world_model = store.world_models.list_by_job(job.id)[0]
    assert len(world_model.states) >= 1
    assert any(w.name == "bounded auto-exploration" for w in world_model.workflows)
    # the "Create Project" button gets clicked, revealing a "Delete" button
    # that must show up as a skipped-destructive candidate, not an auto-click
    assert any("Delete" in u.rationale for u in world_model.unknowns)
