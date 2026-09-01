"""Phase 8 end-to-end: running the same project twice, the second run's
memory recognizes the bug the first run already confirmed, instead of
re-flagging it as a fresh Unknown -- and the persisted Strategy/Learning
mechanism actually gets exercised across the two runs.
"""
from __future__ import annotations

from pathlib import Path

from veriforge.domain.models import Job
from veriforge.events.bus import EventBus
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.job_runner import JobRunner

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


class FakeLLMProvider(LLMProvider):
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        return "fake summary"

    def is_available(self) -> bool:
        return False

    @property
    def model_name(self) -> str:
        return "fake-model"


def test_second_run_recognizes_bug_the_first_run_already_confirmed(store, tmp_path, example_app_server):
    bus = EventBus(store)
    runner = JobRunner(store, bus, FakeLLMProvider(), artifacts_dir=tmp_path / "artifacts")

    shared_project_id = "proj_memory_test"

    job1 = Job(
        project_id=shared_project_id,
        repo_path=str(EXAMPLES_DIR / "example-app"),
        requirements_path=str(EXAMPLES_DIR / "requirements.md"),
        base_url=example_app_server,
    )
    summary1 = runner.run(job1)

    assert summary1.verdict == "FAIL"
    assert summary1.unknowns_resolved_from_memory == 0  # nothing to remember yet
    assert summary1.strategy_version == 1
    assert summary1.learning_kept is None  # first run: no baseline yet

    job2 = Job(
        project_id=shared_project_id,
        repo_path=str(EXAMPLES_DIR / "example-app"),
        requirements_path=str(EXAMPLES_DIR / "requirements.md"),
        base_url=example_app_server,
    )
    summary2 = runner.run(job2)

    # The second run's memory recognizes the same requirement was already
    # confirmed violated by job1 -- its Unknown comes back pre-resolved.
    assert summary2.unknowns_resolved_from_memory >= 1
    assert summary2.strategy_version == 1  # same project -> same persisted strategy, not recreated

    learnings = store.learnings.list_by_project(shared_project_id)
    assert len(learnings) == 2  # one per run
    assert learnings[1].baseline_metric == learnings[0].measured_metric  # 2nd run's baseline = 1st run's metric

    strategies = store.strategies.list_by_project(shared_project_id)
    assert len(strategies) == 1  # reused, not duplicated
