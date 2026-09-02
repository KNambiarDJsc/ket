"""Phase 11 end-to-end: the Executor actually calls the live example-db-app,
and the Oracle reads the SQLite database directly -- not just a follow-up
API GET -- to confirm the intentionally-planted soft-delete bug, with a
full observation/evidence trail. This is the payoff of Phase 11: a bug that
Phase 6's API-only state check could not have seen (the API's own GET
/projects correctly hides the "deleted" row) is only visible once the
Oracle reads the underlying table directly.

Phase 15 added a third, higher-priority (NEGATIVE/security-shaped) candidate
to the same db-requirements.md -- a real, more urgent bug now legitimately
outranks this one, exactly the way Phase 9's second requirement reshuffled
Phase 8's two-run demo. The first test below now runs the same project
twice: run 1 finds and confirms Phase 15's duplicate-creation bug (now
top-ranked), memory (Phase 8/13) resolves it, and run 2's Test Scientist --
with that Unknown excluded -- falls through to exactly the ranking this test
originally verified for the Phase 11 soft-delete bug.
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


def test_executor_confirms_the_planted_soft_delete_bug_via_direct_db_read(store, tmp_path, example_db_app_server):
    base_url, db_path = example_db_app_server
    bus = EventBus(store)
    runner = JobRunner(store, bus, FakeLLMProvider(), artifacts_dir=tmp_path / "artifacts")
    shared_project_id = "proj_db_observation_test"

    job1 = Job(
        project_id=shared_project_id,
        repo_path=str(EXAMPLES_DIR / "example-db-app"),
        requirements_path=str(EXAMPLES_DIR / "db-requirements.md"),
        base_url=base_url,
        db_path=db_path,
    )
    summary1 = runner.run(job1)

    # Phase 15's duplicate-creation check is NEGATIVE/security-shaped and
    # genuinely outranks the Phase 11 soft-delete check -- it executes first.
    assert summary1.final_state == "COMPLETED"
    assert summary1.verdict == "FAIL"
    assert summary1.top_hypothesis == (
        "Verify: A duplicated project-creation request must not create two projects."
    )

    job2 = Job(
        project_id=shared_project_id,
        repo_path=str(EXAMPLES_DIR / "example-db-app"),
        requirements_path=str(EXAMPLES_DIR / "db-requirements.md"),
        base_url=base_url,
        db_path=db_path,
    )
    summary2 = runner.run(job2)

    # Memory (Phase 8/13) resolved run 1's confirmed finding, so run 2's Test
    # Scientist excludes it from ranking -- the Phase 11 soft-delete check is
    # now the top-ranked, executable candidate, exactly as this test verified
    # before Phase 15 added a higher-priority sibling requirement.
    assert summary2.final_state == "COMPLETED"
    assert summary2.unknowns_resolved_from_memory >= 1
    assert summary2.test_count == 1
    assert summary2.verdict == "FAIL"
    assert summary2.finding_count == 1
    assert summary2.top_hypothesis == "Verify: Deleted projects must be permanently removed from the database, not merely hidden."
    assert summary2.reproduced is True  # the soft-delete bug is deterministic, not flaky

    findings = store.findings.list_by_job(job2.id)
    assert len(findings) == 1
    finding = findings[0]
    # A data-integrity bug, not an authorization one -- the Triager classifies
    # by requirement kind (FUNCTIONAL here), not a role-check narrative.
    assert finding.category == FailureCategory.APPLICATION_BUG
    assert finding.confidence >= 0.7
    assert finding.reproduced is True
    assert finding.root_cause is not None
    assert "role/permission-check" not in finding.root_cause
    assert "still physically present" in finding.root_cause
    assert "Reproduced on a second independent run" in finding.root_cause

    observations = store.observations.list_by_job(job2.id)
    first_run_tools = [o.tool for o in observations[:3]]
    assert first_run_tools == ["api.post", "api.delete", "database.query_sqlite"]
    db_obs = observations[2]
    assert db_obs.state_after["row_count"] >= 1  # the row is still there -- only soft-deleted

    tests = store.tests.list_by_job(job2.id)
    executed_test = next(t for t in tests if t.status == TestStatus.BUG_VERIFIED)
    assert executed_test.status == TestStatus.BUG_VERIFIED

    test_runs = store.test_runs.list_by_job(job2.id)
    assert len(test_runs) == 2  # original run + Phase 7's reproduction run
    assert all(tr.verdict == Verdict.FAIL for tr in test_runs)


def test_no_db_path_means_db_check_requirement_stays_unexecuted(store, tmp_path, example_db_app_server):
    base_url, _db_path = example_db_app_server
    bus = EventBus(store)
    runner = JobRunner(store, bus, FakeLLMProvider(), artifacts_dir=tmp_path / "artifacts")

    job = Job(
        project_id="proj_1",
        repo_path=str(EXAMPLES_DIR / "example-db-app"),
        requirements_path=str(EXAMPLES_DIR / "db-requirements.md"),
        base_url=base_url,
        # db_path intentionally omitted
    )

    summary = runner.run(job)

    assert summary.final_state == "COMPLETED"
    # The db_check requirement is skipped (no --db-path); the only other
    # requirement (endpoint-exposure health check) genuinely PASSes instead.
    assert summary.test_count == 1
    assert summary.verdict == "PASS"
    assert summary.finding_count == 0
