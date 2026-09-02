"""Harness Auditor (Phase 16 Evaluation Lab, spec §42): runs VeriForge's own
Executor/Oracle against every *scored* requirement in a ground-truth
benchmark (evaluation/benchmarks.py) -- not just the single top-ranked
candidate a live job run would execute -- and compares each verdict
against a known answer. This is the missing piece `learning/engine.py`'s
own docstring names: a statistically-meaningful comparison across real,
varied, ground-truth-backed checks, so "found a bug" and "raised a false
alarm" are finally distinguishable, instead of judging a Strategy or
harness change on a single, unlabeled run.

Deliberately bypasses `orchestrator.job_runner`'s one-experiment-per-run
loop: that loop's job is to act like a real, budget-conscious agent picking
its single best next move, which is the wrong shape for auditing -- the
Evaluation Lab needs to know how EVERY executable check performs against
its known answer, not just the highest-priority one this run.

Metrics computed per spec §42:
  verified_findings_per_compute  -- confirmed true-positive bugs found,
                                     divided by tool calls spent getting them.
  information_gain_per_experiment -- fraction of scored, executed checks
                                     that produced a decisive PASS/FAIL
                                     rather than UNCERTAIN (an UNCERTAIN
                                     verdict answers nothing about the
                                     requirement it was supposed to check).
  false_positive_rate            -- of the requirements genuinely satisfied
                                     (ground truth PASS), the fraction the
                                     Oracle wrongly flagged FAIL.

With only two benchmark apps and eight scored requirements today, this is
real signal, not noise -- but it is still a small sample. See
`evaluation/gate.py` for how that honesty is preserved in any keep/revert
decision built on top of these numbers.
"""
from __future__ import annotations

import importlib.util
import threading
import uuid
from dataclasses import dataclass
from http.server import HTTPServer
from pathlib import Path

from veriforge.cartography.cartographer import analyze as analyze_repository_facts
from veriforge.domain.enums import Verdict
from veriforge.domain.models import Test
from veriforge.events.bus import EventBus
from veriforge.evaluation.benchmarks import ALL_BENCHMARKS, Benchmark
from veriforge.execution.experiment_runner import is_executable, run_experiment
from veriforge.harness.budget import BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.llm.provider import LLMProvider
from veriforge.requirements.parser import parse_requirements_file
from veriforge.storage import db as db_module
from veriforge.storage.repository import Store
from veriforge.storage.schema import create_all
from veriforge.world_model.builder import build_world_model, match_endpoint_for_requirement


class _NullLLMProvider(LLMProvider):
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        return ""

    def is_available(self) -> bool:
        return False

    @property
    def model_name(self) -> str:
        return "null"


@dataclass
class RequirementAudit:
    source_text: str
    expected: Verdict
    observed: Verdict | None  # None == never became executable against this repo
    reasoning: str | None

    @property
    def outcome(self) -> str:
        if self.observed is None:
            return "not_executable"
        if self.observed == self.expected:
            return "correct"
        if self.expected == Verdict.PASS and self.observed == Verdict.FAIL:
            return "false_positive"
        if self.expected == Verdict.FAIL and self.observed == Verdict.PASS:
            return "false_negative"
        return "inconclusive"  # e.g. UNCERTAIN either way


@dataclass
class BenchmarkResult:
    benchmark_name: str
    audits: list[RequirementAudit]
    tool_calls_used: int

    @property
    def scored_audits(self) -> list[RequirementAudit]:
        return [a for a in self.audits if a.observed is not None]

    @property
    def verified_findings_per_compute(self) -> float:
        if not self.tool_calls_used:
            return 0.0
        true_positives = sum(
            1 for a in self.scored_audits if a.expected == Verdict.FAIL and a.outcome == "correct"
        )
        return true_positives / self.tool_calls_used

    @property
    def information_gain_per_experiment(self) -> float:
        scored = self.scored_audits
        if not scored:
            return 0.0
        decisive = sum(1 for a in scored if a.observed in (Verdict.PASS, Verdict.FAIL))
        return decisive / len(scored)

    @property
    def false_positive_rate(self) -> float:
        pass_ground_truth = [a for a in self.scored_audits if a.expected == Verdict.PASS]
        if not pass_ground_truth:
            return 0.0
        false_positives = sum(1 for a in pass_ground_truth if a.outcome == "false_positive")
        return false_positives / len(pass_ground_truth)


def _load_app_module(app_module_path: Path):
    # A unique module name per call: the same app.py (e.g. example-db-app's)
    # may be audited more than once in one process (see gate.py's A/B
    # comparison), and Python caches modules by name in sys.modules.
    spec = importlib.util.spec_from_file_location(f"veriforge_eval_{uuid.uuid4().hex[:8]}", app_module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _start_benchmark_app(benchmark: Benchmark, workdir: Path):
    module = _load_app_module(benchmark.app_module_path)
    db_path = None
    if benchmark.needs_db:
        db_path = str(workdir / f"{benchmark.name}.db")
        module.DB_PATH = db_path
        module.init_db(db_path)
    elif hasattr(module, "PROJECTS"):
        # example-app keeps its state in a module-level dict -- a fresh
        # module_from_spec load already gives it an empty one, but clearing
        # explicitly documents the assumption rather than relying on it.
        module.PROJECTS.clear()
    server = HTTPServer(("127.0.0.1", 0), module.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{port}", db_path


def run_benchmark(benchmark: Benchmark, workdir: Path) -> BenchmarkResult:
    """Starts the benchmark's real app, executes every scored ground-truth
    requirement directly (not gated to one-per-run, and not ranked --
    `strategist.scientist`'s weights only affect which candidate a live job
    run picks *first*, never the Executor/Oracle verdict itself, so they
    have nothing to contribute to an audit that runs every candidate
    anyway), and compares each verdict to the known answer.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    server, thread, base_url, db_path = _start_benchmark_app(benchmark, workdir)
    try:
        db_module.reset_engine_cache()
        engine = db_module.get_engine(workdir)
        create_all(engine)
        session = db_module.get_session(workdir)
        store = Store(session)
        try:
            registry = ToolRegistry()
            register_builtin_tools(registry, _NullLLMProvider())
            bus = EventBus(store)
            budget = BudgetTracker.new(f"eval_{benchmark.name}")
            executor = ToolExecutor(registry, PermissionPolicy(), budget, bus, f"eval_{benchmark.name}")
            try:
                requirements = parse_requirements_file(str(benchmark.requirements_path), benchmark.name)
                repo_facts = analyze_repository_facts(str(benchmark.repo_path))
                world_model = build_world_model(benchmark.name, requirements, repo_facts)
                requirements_by_text = {r.source_text: r for r in world_model.requirements}

                audits: list[RequirementAudit] = []
                for gt in benchmark.ground_truth:
                    if gt.expected_verdict is None:
                        continue  # not yet executable by design -- excluded from scoring
                    requirement = requirements_by_text.get(gt.source_text)
                    endpoint = (
                        match_endpoint_for_requirement(requirement, world_model.api_endpoints)
                        if requirement else None
                    )
                    if requirement is None or endpoint is None or not is_executable(requirement):
                        audits.append(RequirementAudit(gt.source_text, gt.expected_verdict, None, None))
                        continue

                    test = Test(project_id=benchmark.name, name=requirement.source_text)
                    result = run_experiment(
                        base_url=base_url, requirement=requirement, endpoint=endpoint,
                        all_endpoints=world_model.api_endpoints, tool_executor=executor,
                        test=test, db_path=db_path,
                    )
                    audits.append(RequirementAudit(
                        gt.source_text, gt.expected_verdict,
                        result.oracle_verdict.verdict, result.oracle_verdict.reasoning,
                    ))

                return BenchmarkResult(
                    benchmark_name=benchmark.name, audits=audits, tool_calls_used=budget.tool_calls_used,
                )
            finally:
                executor.shutdown()
        finally:
            store.close()
            # Windows holds the sqlite file open via the engine's connection
            # pool even after the session closes -- without disposing it
            # explicitly, a caller that then tries to remove `workdir`
            # (e.g. a tempdir context manager) gets a bare PermissionError.
            engine.dispose()
            db_module.reset_engine_cache()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def run_all_benchmarks(workdir: Path) -> list[BenchmarkResult]:
    return [run_benchmark(b, workdir / b.name) for b in ALL_BENCHMARKS]


def aggregate_metrics(results: list[BenchmarkResult]) -> dict[str, float]:
    """Pools every benchmark's audits into one set of numbers -- the
    Evaluation Lab's overall score, not a per-app breakdown (that's what
    BenchmarkResult itself is for)."""
    all_audits = [a for r in results for a in r.audits]
    total_tool_calls = sum(r.tool_calls_used for r in results)
    scored = [a for a in all_audits if a.observed is not None]

    true_positives = sum(1 for a in scored if a.expected == Verdict.FAIL and a.outcome == "correct")
    decisive = sum(1 for a in scored if a.observed in (Verdict.PASS, Verdict.FAIL))
    pass_ground_truth = [a for a in scored if a.expected == Verdict.PASS]
    false_positives = sum(1 for a in pass_ground_truth if a.outcome == "false_positive")

    return {
        "scored_requirement_count": float(len(scored)),
        "verified_findings_per_compute": (true_positives / total_tool_calls) if total_tool_calls else 0.0,
        "information_gain_per_experiment": (decisive / len(scored)) if scored else 0.0,
        "false_positive_rate": (false_positives / len(pass_ground_truth)) if pass_ground_truth else 0.0,
    }
