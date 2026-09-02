from veriforge.domain.enums import FailureCategory, RequirementKind, Verdict
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.events.bus import EventBus
from veriforge.execution.experiment_runner import run_experiment
from veriforge.harness.budget import BudgetTracker
from veriforge.harness.builtin_tools import register_builtin_tools
from veriforge.harness.executor import ToolExecutor
from veriforge.harness.permissions import PermissionPolicy
from veriforge.harness.tools import ToolRegistry
from veriforge.investigation.investigator import build_root_cause
from veriforge.investigation.reproducer import reproduce
from veriforge.investigation.triager import triage
from veriforge.llm.provider import LLMProvider
from veriforge.oracle.oracle import OracleVerdict


class NullLLM(LLMProvider):
    def generate(self, prompt, *, system=None):
        return ""

    def is_available(self):
        return False

    @property
    def model_name(self):
        return "null"


def make_executor(store):
    registry = ToolRegistry()
    register_builtin_tools(registry, NullLLM())
    bus = EventBus(store)
    budget = BudgetTracker.new("job_1")
    return ToolExecutor(registry, PermissionPolicy(), budget, bus, "job_1")


def authz_requirement(kind=RequirementKind.NEGATIVE):
    return Requirement(
        project_id="p", source_text="Members cannot delete projects.", kind=kind, critical=True,
        structured={"actor": "members", "action": "delete", "object": "projects", "expected": "denied"},
    )


# ---- triager ----

def test_triage_high_confidence_authz_fail_is_security_finding():
    verdict = OracleVerdict(Verdict.FAIL, 0.9, "denied", "allowed", "reasoning text")
    category, reasoning = triage(verdict, authz_requirement())
    assert category == FailureCategory.SECURITY_FINDING
    assert "reasoning text" in reasoning


def test_triage_low_confidence_fail_is_requirement_ambiguity():
    verdict = OracleVerdict(Verdict.FAIL, 0.6, "denied", "allowed", "status/state disagreed")
    category, _ = triage(verdict, authz_requirement())
    assert category == FailureCategory.REQUIREMENT_AMBIGUITY


def test_triage_uncertain_verdict_is_requirement_ambiguity():
    verdict = OracleVerdict(Verdict.UNCERTAIN, 0.3, "denied", "unknown", "ambiguous status")
    category, _ = triage(verdict, authz_requirement())
    assert category == FailureCategory.REQUIREMENT_AMBIGUITY


def test_triage_non_security_kind_is_application_bug():
    verdict = OracleVerdict(Verdict.FAIL, 0.9, "denied", "allowed", "reasoning text")
    category, _ = triage(verdict, authz_requirement(kind=RequirementKind.FUNCTIONAL))
    assert category == FailureCategory.APPLICATION_BUG


# ---- reproducer + investigator (need the real example app) ----

def test_reproduce_confirms_deterministic_bug_is_reproducible(store, example_app_server):
    executor = make_executor(store)
    endpoints = [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=1),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2, mentions_role_check=False),
    ]
    requirement = authz_requirement()
    from veriforge.domain.models import Test
    test = Test(project_id="p", experiment_id="exp_1", name=requirement.source_text)

    first = run_experiment(
        base_url=example_app_server, requirement=requirement, endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test=test,
    )
    assert first.oracle_verdict.verdict == Verdict.FAIL

    reproduction = reproduce(
        base_url=example_app_server, requirement=requirement, endpoint=endpoints[1],
        all_endpoints=endpoints, tool_executor=executor, test=test,
        first_verdict=first.oracle_verdict.verdict,
    )

    assert reproduction.reproducible is True
    assert reproduction.second_run.oracle_verdict.verdict == Verdict.FAIL
    assert len(reproduction.second_run.observations) == 4

    root_cause = build_root_cause(endpoints[1], first.oracle_verdict, reproduction)
    assert "no role/permission-check identifier" in root_cause
    assert "Reproduced on a second independent run" in root_cause
    executor.shutdown()


def test_investigator_notes_when_endpoint_does_mention_role_check():
    checked_endpoint = ApiEndpoint(
        project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2, mentions_role_check=True,
    )
    verdict = OracleVerdict(Verdict.FAIL, 0.9, "denied", "allowed", "reasoning")
    root_cause = build_root_cause(checked_endpoint, verdict, reproduction=None)
    assert "DOES reference a role/permission-looking identifier" in root_cause
    assert "needs code review" in root_cause


def test_investigator_omits_role_check_note_for_non_authorization_requirement():
    # Phase 10/11: a contract or DB-integrity Finding isn't about role checks
    # at all -- grafting that commentary on would be a non-sequitur.
    endpoint = ApiEndpoint(
        project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=75, mentions_role_check=False,
    )
    verdict = OracleVerdict(Verdict.FAIL, 0.9, "not present in the database", "still present", "reasoning")
    db_check_requirement = Requirement(
        project_id="p", source_text="Deleted projects must be permanently removed from the database.",
        kind=RequirementKind.FUNCTIONAL, critical=True,
        structured={"db_check": "removed_after_delete", "object": "projects", "action": "delete"},
    )
    root_cause = build_root_cause(endpoint, verdict, reproduction=None, requirement=db_check_requirement)
    assert "role/permission-check" not in root_cause
    assert root_cause == "reasoning"
