"""Phase 6 end-to-end: the Executor actually calls the live example app and
the Oracle actually confirms the intentionally-planted authorization bug,
with a full observation/evidence trail -- not a simulated or hardcoded
result. This is the payoff of Phases 3-6 working together.
"""
from __future__ import annotations

from pathlib import Path

from veriforge.domain.enums import FailureCategory, TestStatus, Verdict
from veriforge.domain.models import Job
from veriforge.events.bus import EventBus
from veriforge.llm.provider import LLMProvider
from veriforge.orchestrator.job_runner import JobRunner
from veriforge.storage.repository import Store

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


class FakeLLMProvider(LLMProvider):
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        return "fake summary"

    def is_available(self) -> bool:
        return False

    @property
    def model_name(self) -> str:
        return "fake-model"


def test_executor_confirms_the_planted_authorization_bug(store, tmp_path, example_app_server):
    bus = EventBus(store)
    runner = JobRunner(store, bus, FakeLLMProvider(), artifacts_dir=tmp_path / "artifacts")

    job = Job(
        project_id="proj_1",
        repo_path=str(EXAMPLES_DIR / "example-app"),
        requirements_path=str(EXAMPLES_DIR / "requirements.md"),
        base_url=example_app_server,
    )

    summary = runner.run(job)

    assert summary.final_state == "COMPLETED"
    assert summary.test_count == 1
    assert summary.verdict == "FAIL"
    assert summary.finding_count == 1
    assert summary.top_hypothesis == "Verify: Members cannot delete projects."

    assert summary.reproduced is True  # the app's bug is deterministic, not flaky

    findings = store.findings.list_by_job(job.id)
    assert len(findings) == 1
    finding = findings[0]
    # Set by Phase 7's Triager (high-confidence FAIL on a NEGATIVE/authorization
    # requirement), not by run_experiment directly.
    assert finding.category == FailureCategory.SECURITY_FINDING
    assert finding.confidence >= 0.7
    assert finding.reproduced is True
    assert finding.root_cause is not None
    assert "no role/permission-check identifier" in finding.root_cause
    assert "Reproduced on a second independent run" in finding.root_cause
    assert len(finding.evidence_ids) == 4  # create, check-before, delete, check-after (first run only)

    # First run's 4 observations + Phase 7's reproduction run's 4 more.
    observations = store.observations.list_by_job(job.id)
    assert len(observations) == 8
    first_run_tools = [o.tool for o in observations[:4]]
    assert first_run_tools == ["api.post", "api.get", "api.delete", "api.get"]
    delete_obs = observations[2]
    assert "role='member'" in delete_obs.action
    assert delete_obs.state_after["status"] == 200  # the app wrongly allowed it

    tests = store.tests.list_by_job(job.id)
    executed_test = next(t for t in tests if t.status == TestStatus.BUG_VERIFIED)
    assert executed_test.status == TestStatus.BUG_VERIFIED  # reproduced -> graduated past FAILED

    test_runs = store.test_runs.list_by_job(job.id)
    assert len(test_runs) == 2  # original run + Phase 7's reproduction run
    assert all(tr.verdict == Verdict.FAIL for tr in test_runs)
    assert all(tr.finished_at is not None for tr in test_runs)

    for artifact_name in ("observations.json", "verdict.json", "finding.json", "investigation.json"):
        assert any(p.endswith(artifact_name) for p in summary.artifact_paths)


def test_no_base_url_means_nothing_executed(store, tmp_path):
    bus = EventBus(store)
    runner = JobRunner(store, bus, FakeLLMProvider(), artifacts_dir=tmp_path / "artifacts")

    job = Job(
        project_id="proj_1",
        repo_path=str(EXAMPLES_DIR / "example-app"),
        requirements_path=str(EXAMPLES_DIR / "requirements.md"),
    )
    summary = runner.run(job)

    assert summary.test_count == 0
    assert summary.verdict is None
    assert summary.finding_count == 0
    assert store.findings.list_by_job(job.id) == []
