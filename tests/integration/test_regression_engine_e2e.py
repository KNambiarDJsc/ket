"""Phase 13 end-to-end: a BUG_VERIFIED finding against the live DB-backed
example app gets a permanent, executable regression test written into a
*copy* of that app's own repo (never the tracked examples/ directory, so
running this test suite never pollutes the real fixture) -- and that
generated file is actually run via a real `pytest` subprocess, not just
checked for valid syntax, to prove it's genuinely executable and correctly
asserts the fix (so it currently fails, since the bug is still there).

Phase 15 added a third, higher-priority (NEGATIVE/security-shaped)
requirement to the same db-requirements.md, so the single top-ranked
experiment this test's one job run executes and regresses is now that one
(the duplicate-creation/idempotency bug) rather than Phase 11's soft-delete
bug -- see tests/integration/test_db_observation.py's own updated docstring
for the same ranking shift, handled there with a two-run sequence instead
since that test specifically exists to verify the Phase 11 bug.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import threading
from pathlib import Path

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


def _copy_db_app(tmp_path: Path) -> Path:
    target = tmp_path / "target-db-app"
    shutil.copytree(
        EXAMPLES_DIR / "example-db-app", target,
        ignore=shutil.ignore_patterns("__pycache__", "*.db"),
    )
    return target


def _start_copied_app(app_dir: Path):
    spec = importlib.util.spec_from_file_location("veriforge_copied_db_app", app_dir / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db_path = str(app_dir / "data.db")
    module.DB_PATH = db_path
    module.init_db(db_path)
    server = module.HTTPServer(("localhost", 0), module.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://localhost:{port}", db_path


def test_bug_verified_finding_writes_an_executable_regression_test(store, tmp_path):
    target_repo = _copy_db_app(tmp_path)
    server, thread, base_url, db_path = _start_copied_app(target_repo)
    try:
        bus = EventBus(store)
        runner = JobRunner(store, bus, FakeLLMProvider(), artifacts_dir=tmp_path / "artifacts", write_regressions=True)

        job = Job(
            project_id="proj_1",
            repo_path=str(target_repo),
            requirements_path=str(EXAMPLES_DIR / "db-requirements.md"),
            base_url=base_url,
            db_path=db_path,
        )
        summary = runner.run(job)

        assert summary.verdict == "FAIL"
        assert summary.regression_test_path is not None
        regression_path = Path(summary.regression_test_path)
        assert regression_path.exists()
        assert regression_path.is_relative_to(target_repo)  # never written outside the target repo

        findings = store.findings.list_by_job(job.id)
        assert findings[0].regression_test_path == str(regression_path)

        # Prove it's genuinely executable, not just syntactically valid --
        # run it for real via pytest. It should FAIL: example-db-app has no
        # idempotency protection, so the regression assertion (expects
        # PASS) doesn't hold yet.
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(regression_path), "-q"],
            cwd=str(target_repo),
            env={**_inherited_env(), "VERIFORGE_BASE_URL": base_url, "VERIFORGE_DB_PATH": db_path},
            capture_output=True, text=True, timeout=60,
        )
        assert "1 failed" in result.stdout, result.stdout + result.stderr
        assert "no idempotency protection" in result.stdout
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _inherited_env() -> dict:
    import os
    return dict(os.environ)
