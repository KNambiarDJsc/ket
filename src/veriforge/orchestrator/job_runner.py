"""Drives a Job through its full lifecycle.

JOB_CREATED -> REQUIREMENTS_RECEIVED -> JOB_INITIALIZED -> ANALYSIS_PENDING
  -> WORLD_MODEL_PENDING -> TESTING_PENDING -> COMPLETED

Every step does real work (parses the actual requirements file, walks the
actual repo, persists actual rows) rather than returning a placeholder.
TESTING_PENDING intentionally runs zero experiments in Phase 1 — the
Test Scientist/Executor/Oracle don't exist yet (Phase 5/6) — and says so
explicitly in the run summary rather than faking findings.

As of Phase 2, every capability that touches the filesystem, network, or the
LLM goes through the harness (ToolRegistry + PermissionPolicy + BudgetTracker
+ ToolExecutor) instead of being called directly — this is the mechanism
future agents (Phase 3+) will also use, exercised here for real rather than
left as unused scaffolding.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from veriforge.context.compiler import ContextCompiler
from veriforge.domain.enums import EventType, FailureCategory, JobState, TestStatus, Verdict
from veriforge.domain.models import Artifact, Evidence, Job, utcnow
from veriforge.events.bus import EventBus
from veriforge.execution.experiment_runner import is_executable, run_experiment
from veriforge.harness.budget import BudgetExceededError, BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor, ToolTimeoutError
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.investigation.investigator import build_root_cause
from veriforge.investigation.reproducer import reproduce
from veriforge.investigation.triager import triage
from veriforge.learning.engine import compute_run_metric, record_run_learning
from veriforge.llm.provider import LLMProvider, LLMUnavailableError
from veriforge.memory.procedural import get_active_strategy
from veriforge.memory.semantic import apply_semantic_memory
from veriforge.orchestrator.state_machine import JobStateMachine
from veriforge.requirements.parser import parse_requirements_file
from veriforge.storage.repository import Store
from veriforge.strategist.scientist import promote_to_tests, rank_experiments
from veriforge.world_model.builder import build_world_model, match_endpoint_for_requirement


@dataclass
class RunSummary:
    job_id: str
    final_state: str
    duration_seconds: float
    requirement_count: int
    critical_requirement_count: int
    unknown_count: int
    pages_explored: int
    hypotheses_generated: int
    top_hypothesis: str | None
    test_count: int
    finding_count: int
    verdict: str | None
    reproduced: bool | None
    strategy_version: int
    unknowns_resolved_from_memory: int
    learning_kept: bool | None
    artifact_paths: list[str]
    event_count: int
    tool_calls_used: int
    next_phase: str


class JobRunner:
    def __init__(
        self,
        store: Store,
        bus: EventBus,
        llm: LLMProvider,
        artifacts_dir: str | Path,
        *,
        permission_policy: PermissionPolicy | None = None,
        max_tool_calls: int = 50,
        max_runtime_seconds: float = 900.0,
    ):
        self._store = store
        self._bus = bus
        self._llm = llm
        self._sm = JobStateMachine(bus)
        self._artifacts_root = Path(artifacts_dir)
        self._policy = permission_policy or PermissionPolicy()
        self._max_tool_calls = max_tool_calls
        self._max_runtime_seconds = max_runtime_seconds
        self._registry = ToolRegistry()
        register_builtin_tools(self._registry, llm)

    def _write_artifact(self, job: Job, kind: str, data: dict) -> Artifact:
        job_dir = self._artifacts_root / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / kind
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        artifact = Artifact(job_id=job.id, kind=kind, path=str(path))
        self._store.artifacts.save(artifact, job_id=job.id)
        self._bus.publish(job.id, EventType.ARTIFACT_WRITTEN, {"kind": kind, "path": str(path)})
        return artifact

    def run(self, job: Job) -> RunSummary:
        started = utcnow()
        self._store.jobs.save(job, job_id=job.id, project_id=job.project_id)

        budget = BudgetTracker.new(
            job.id, max_tool_calls=self._max_tool_calls, max_runtime_seconds=self._max_runtime_seconds
        )
        self._executor = ToolExecutor(self._registry, self._policy, budget, self._bus, job.id, agent_name="job_runner")
        self._budget = budget

        try:
            self._step_requirements(job)
            self._step_initialize(job)
            self._step_analysis(job)
            self._step_world_model(job)
            self._step_testing(job)
            self._sm.transition(job, JobState.COMPLETED, reason="phase-1 lifecycle complete")
        except Exception as exc:  # noqa: BLE001 - job failures must be recorded, not raised silently
            job.error = str(exc)
            if job.state != JobState.FAILED:
                job.state = JobState.FAILED
            self._bus.publish(job.id, EventType.JOB_FAILED, {"error": str(exc)})
            self._store.jobs.save(job, job_id=job.id, project_id=job.project_id)
            raise
        finally:
            self._store.jobs.save(job, job_id=job.id, project_id=job.project_id)
            self._store.loop_states.save(budget.state, job_id=job.id)
            self._executor.shutdown()

        return self._summarize(job, started)

    def _step_requirements(self, job: Job) -> None:
        requirements = []
        if job.requirements_path:
            requirements = parse_requirements_file(job.requirements_path, job.project_id)
            for req in requirements:
                self._store.requirements.save(req, job_id=job.id, project_id=job.project_id)
        self._write_artifact(
            job,
            "requirements.json",
            {"count": len(requirements), "requirements": [r.model_dump(mode="json") for r in requirements]},
        )
        self._bus.publish(
            job.id, EventType.REQUIREMENT_PARSED, {"count": len(requirements)}
        )
        self._sm.transition(job, JobState.REQUIREMENTS_RECEIVED, reason=f"parsed {len(requirements)} requirements")

    def _step_initialize(self, job: Job) -> None:
        checks: dict[str, object] = {}
        if job.repo_path:
            checks["repo_exists"] = Path(job.repo_path).exists()
        if job.base_url:
            try:
                resp = self._executor.call("api.get", url=job.base_url)
                checks["url_reachable"] = resp.status_code < 500
                checks["url_status"] = resp.status_code
            except (httpx.HTTPError, ToolTimeoutError) as exc:
                checks["url_reachable"] = False
                checks["url_error"] = str(exc)
        self._write_artifact(job, "initialization.json", checks)
        self._sm.transition(job, JobState.JOB_INITIALIZED, reason="preflight checks recorded")

    def _step_analysis(self, job: Job) -> None:
        repo_facts: dict = {}
        if job.repo_path:
            repo_facts = self._executor.call("code.analyze_repository", repo_path=job.repo_path)

        llm_summary = None
        if repo_facts and self._llm.is_available():
            try:
                prompt = (
                    "You are analyzing a software repository for a QA system. "
                    "Given these raw facts (JSON), write a 2-3 sentence plain-"
                    "English summary of what kind of project this looks like. "
                    "Do not invent facts not present in the JSON.\n\n"
                    f"{json.dumps(repo_facts)}"
                )
                llm_summary = self._executor.call("llm.generate", prompt=prompt, system=None)
            except (LLMUnavailableError, ToolTimeoutError):
                llm_summary = None
            except BudgetExceededError:
                llm_summary = None

        analysis = {"repo_facts": repo_facts, "llm_summary": llm_summary, "model": self._llm.model_name}
        self._write_artifact(job, "analysis.json", analysis)
        self._bus.publish(job.id, EventType.ANALYSIS_COMPLETED, {"has_repo_facts": bool(repo_facts)})
        self._repo_facts = repo_facts
        self._sm.transition(job, JobState.ANALYSIS_PENDING, reason="repository scanned")

    def _step_world_model(self, job: Job) -> None:
        requirements = self._store.requirements.list_by_job(job.id)

        exploration = None
        if job.base_url:
            try:
                exploration = self._executor.call(
                    "browser.explore",
                    url=job.base_url,
                    screenshot_dir=str(self._artifacts_root / job.id / "screenshots"),
                )
            except BudgetExceededError:
                raise  # a spent budget should stop the job, not be swallowed
            except Exception as exc:  # noqa: BLE001 - a dead/unreachable/misbehaving
                # target is an ENVIRONMENT_FAILURE (spec's failure taxonomy), not a
                # reason to fail the whole verification job; record it honestly.
                self._write_artifact(job, "exploration.json", {"error": str(exc)})

        if exploration is not None:
            self._write_artifact(job, "exploration.json", asdict(exploration))

        world_model = build_world_model(job.project_id, requirements, getattr(self, "_repo_facts", {}), exploration)

        # Phase 8 semantic memory: if a prior run of this same project already
        # produced a Finding for one of these requirements, mark its Unknown
        # resolved now rather than re-flagging an already-confirmed bug as
        # fresh every single run.
        resolved_from_memory = apply_semantic_memory(self._store, world_model)
        self._resolved_from_memory = resolved_from_memory
        if resolved_from_memory:
            self._bus.publish(job.id, EventType.WORLD_MODEL_UPDATED, {"resolved_from_memory": resolved_from_memory})

        self._store.world_models.save(world_model, job_id=job.id, project_id=job.project_id)
        for req in requirements:  # persist the .structured field the builder just populated
            self._store.requirements.save(req, job_id=job.id, project_id=job.project_id)
        self._write_artifact(job, "world-model.json", world_model.model_dump(mode="json"))

        # First real use of the Context Compiler: a task-scoped, budget-aware
        # slice of the world model rather than the whole thing. Persisted as
        # its own artifact so it's inspectable even though no agent consumes
        # it yet (Phase 3+ agents will call ContextCompiler.compile directly).
        bundle = ContextCompiler().compile(
            world_model,
            goal="Verify all critical requirements before release",
            tool_registry=self._registry,
            constraints={
                "tool_calls_used": self._budget.tool_calls_used,
                "max_tool_calls": self._budget.max_tool_calls,
            },
        )
        self._write_artifact(job, "context-bundle.json", {"rendered": bundle.render_prompt()})

        self._bus.publish(
            job.id,
            EventType.WORLD_MODEL_UPDATED,
            {"unknown_count": len(world_model.unknowns), "requirement_count": len(requirements)},
        )
        self._world_model = world_model
        self._sm.transition(job, JobState.WORLD_MODEL_PENDING, reason="world model built")

    def _step_testing(self, job: Job) -> None:
        world_model = getattr(self, "_world_model", None)

        # Phase 8 procedural memory: this project's persisted, versioned
        # scoring weights drive ranking instead of the Strategist's bare
        # DEFAULT_WEIGHTS -- a real hook for a future evaluated weight change
        # (Phase 17) to actually take effect on the next run.
        strategy = get_active_strategy(self._store, job.project_id)
        experiments = rank_experiments(world_model, weights=strategy.weights) if world_model else []
        tests = promote_to_tests(experiments, top_k=3)

        for experiment in experiments:
            self._store.experiments.save(experiment, job_id=job.id, project_id=job.project_id)
        for test in tests:
            self._store.tests.save(test, job_id=job.id, project_id=job.project_id)

        execution = self._execute_top_experiment(job, world_model, experiments, tests)

        metric = compute_run_metric(execution["executed_count"], execution["verdict"])
        learning = record_run_learning(self._store, job.project_id, strategy, job, metric)
        self._write_artifact(job, "learning.json", learning.model_dump(mode="json"))
        self._learning = learning

        self._write_artifact(
            job,
            "hypotheses.json",
            {
                "experiments_run": execution["executed_count"],
                "hypotheses_generated": len(experiments),
                "planned_for_next_execution": sum(1 for t in tests if t.status == TestStatus.PLANNED),
                "ranked_experiments": [e.model_dump(mode="json") for e in experiments],
                "execution_note": execution["note"],
                "strategy_version": strategy.version,
            },
        )
        self._experiments = experiments
        self._execution = execution
        self._strategy = strategy
        self._sm.transition(
            job, JobState.TESTING_PENDING,
            reason=f"generated {len(experiments)} candidate experiments, executed {execution['executed_count']}",
        )

    def _execute_top_experiment(self, job: Job, world_model, experiments: list, tests: list) -> dict:
        """Runs exactly the single highest-ranked *executable* experiment —
        one experiment per iteration, per the master loop's ACT/OBSERVE/
        VERIFY cycle (spec §4). Everything else stays queued for a future
        iteration; this is Phase 8's continuous-loop territory, not Phase 6's."""
        not_run = {"executed_count": 0, "finding": None, "verdict": None, "reproduced": None}
        if world_model is None:
            return {**not_run, "note": "no world model available"}
        if not job.base_url:
            return {**not_run, "note": "no --url provided; nothing live to execute against"}

        requirements_by_id = {r.id: r for r in world_model.requirements}
        tests_by_experiment_id = {t.experiment_id: t for t in tests}

        for experiment in experiments:
            requirement = requirements_by_id.get(experiment.requirement_id) if experiment.requirement_id else None
            if not is_executable(requirement):
                continue
            endpoint = match_endpoint_for_requirement(requirement, world_model.api_endpoints)
            if endpoint is None:
                continue

            test = tests_by_experiment_id.get(experiment.id)
            test.status = TestStatus.EXECUTING
            self._store.tests.save(test, job_id=job.id, project_id=job.project_id)

            try:
                result = run_experiment(
                    base_url=job.base_url,
                    requirement=requirement,
                    endpoint=endpoint,
                    all_endpoints=world_model.api_endpoints,
                    tool_executor=self._executor,
                    test=test,
                )
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001 - a live-target failure is an
                # ENVIRONMENT_FAILURE, not a reason to fail the whole job.
                test.status = TestStatus.PLANNED  # revert -- this attempt didn't produce a result
                self._store.tests.save(test, job_id=job.id, project_id=job.project_id)
                return {**not_run, "note": f"execution attempt failed: {exc}"}

            for obs in result.observations:
                self._store.observations.save(obs, job_id=job.id, project_id=job.project_id)
            self._store.test_runs.save(result.test_run, job_id=job.id, project_id=job.project_id)

            test.status = TestStatus.FAILED if result.oracle_verdict.verdict == Verdict.FAIL else TestStatus.VERIFIED
            self._store.tests.save(test, job_id=job.id, project_id=job.project_id)

            finding_dict = None
            investigation_dict = None
            if result.finding is not None:
                investigation_dict = self._investigate_finding(job, requirement, endpoint, world_model, test, result)
                evidences = [
                    self._store.evidence.save(
                        Evidence(finding_id=result.finding.id, kind="api_observation", uri=f"observation:{obs.id}"),
                        job_id=job.id, project_id=job.project_id,
                    )
                    for obs in result.observations
                ]
                result.finding.evidence_ids = [e.id for e in evidences]
                self._store.findings.save(result.finding, job_id=job.id, project_id=job.project_id)
                finding_dict = result.finding.model_dump(mode="json")

            self._write_artifact(
                job, "observations.json",
                {"test_run_id": result.test_run.id, "observations": [o.model_dump(mode="json") for o in result.observations]},
            )
            self._write_artifact(
                job, "verdict.json",
                {
                    "verdict": result.oracle_verdict.verdict.value,
                    "confidence": result.oracle_verdict.confidence,
                    "expected": result.oracle_verdict.expected,
                    "observed": result.oracle_verdict.observed,
                    "reasoning": result.oracle_verdict.reasoning,
                    "experiment_id": experiment.id,
                    "requirement": requirement.source_text,
                },
            )
            self._write_artifact(job, "finding.json", {"finding": finding_dict})
            if investigation_dict is not None:
                self._write_artifact(job, "investigation.json", investigation_dict)

            return {
                "executed_count": 1,
                "finding": result.finding,
                "verdict": result.oracle_verdict.verdict.value,
                "reproduced": investigation_dict["reproducible"] if investigation_dict else None,
                "note": f"executed '{experiment.hypothesis}' -> {result.oracle_verdict.verdict.value}",
            }

        return {**not_run, "note": "no candidate experiment resolved to an executable (endpoint-matched, expected='denied') check"}

    def _investigate_finding(self, job: Job, requirement, endpoint, world_model, test, result) -> dict:
        """Phase 7: Triager classifies, Reproducer re-runs the check once
        more, Investigator ties static+dynamic evidence into a root cause.
        Only called when Phase 6 already produced a FAIL and a Finding."""
        category, triage_reasoning = triage(result.oracle_verdict, requirement)

        try:
            reproduction = reproduce(
                base_url=job.base_url,
                requirement=requirement,
                endpoint=endpoint,
                all_endpoints=world_model.api_endpoints,
                tool_executor=self._executor,
                test=test,
                first_verdict=result.oracle_verdict.verdict,
            )
        except BudgetExceededError:
            raise
        except Exception as exc:  # noqa: BLE001 - reproduction failing outright is itself signal, not a crash
            result.finding.category = category
            result.finding.root_cause = f"{triage_reasoning} Reproduction attempt failed: {exc}"
            test.status = TestStatus.TRIAGED
            self._store.tests.save(test, job_id=job.id, project_id=job.project_id)
            return {
                "category": category.value, "triage_reasoning": triage_reasoning,
                "reproducible": None, "reproduction_error": str(exc),
            }

        for obs in reproduction.second_run.observations:
            self._store.observations.save(obs, job_id=job.id, project_id=job.project_id)
        self._store.test_runs.save(reproduction.second_run.test_run, job_id=job.id, project_id=job.project_id)

        if not reproduction.reproducible:
            category = FailureCategory.FLAKINESS

        root_cause = build_root_cause(endpoint, result.oracle_verdict, reproduction)
        result.finding.category = category
        result.finding.root_cause = root_cause
        result.finding.reproduced = reproduction.reproducible
        test.status = TestStatus.BUG_VERIFIED if reproduction.reproducible else TestStatus.TRIAGED
        self._store.tests.save(test, job_id=job.id, project_id=job.project_id)

        return {
            "category": category.value,
            "triage_reasoning": triage_reasoning,
            "root_cause": root_cause,
            "reproducible": reproduction.reproducible,
            "second_run_verdict": reproduction.second_run.oracle_verdict.verdict.value,
        }

    def _summarize(self, job: Job, started) -> RunSummary:
        events = self._bus.history(job.id)
        artifacts = self._store.artifacts.list_by_job(job.id)
        world_model = getattr(self, "_world_model", None)
        requirements = world_model.requirements if world_model else []
        unknowns = world_model.unknowns if world_model else []
        states = world_model.states if world_model else []
        experiments = getattr(self, "_experiments", [])
        execution = getattr(self, "_execution", {"executed_count": 0, "finding": None, "verdict": None, "reproduced": None})
        duration = (utcnow() - started).total_seconds()
        summary = RunSummary(
            job_id=job.id,
            final_state=job.state.value,
            duration_seconds=duration,
            requirement_count=len(requirements),
            critical_requirement_count=sum(1 for r in requirements if r.critical),
            unknown_count=len(unknowns),
            pages_explored=len(states),
            hypotheses_generated=len(experiments),
            top_hypothesis=experiments[0].hypothesis if experiments else None,
            test_count=execution["executed_count"],
            finding_count=1 if execution["finding"] else 0,
            verdict=execution["verdict"],
            reproduced=execution.get("reproduced"),
            strategy_version=getattr(self, "_strategy", None).version if getattr(self, "_strategy", None) else 0,
            unknowns_resolved_from_memory=getattr(self, "_resolved_from_memory", 0),
            learning_kept=getattr(self, "_learning", None).kept if getattr(self, "_learning", None) else None,
            artifact_paths=[a.path for a in artifacts],
            event_count=len(events),
            tool_calls_used=self._budget.tool_calls_used,
            next_phase="Phase 10 (API/Integration/System testing breadth: multi-endpoint contract checks)",
        )
        self._write_artifact(job, "run-summary.json", summary.__dict__)
        return summary
