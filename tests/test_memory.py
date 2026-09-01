from veriforge.domain.enums import FailureCategory
from veriforge.domain.models import Finding, Job, Requirement, Unknown, WorldModel
from veriforge.memory.episodic import get_past_findings, get_run_history
from veriforge.memory.procedural import get_active_strategy
from veriforge.memory.semantic import apply_semantic_memory, prior_findings_by_requirement
from veriforge.strategist.scientist import DEFAULT_WEIGHTS


def test_get_run_history_sorted_oldest_first(store):
    j1 = Job(project_id="p1")  # constructed first -> earlier created_at
    j2 = Job(project_id="p1")
    store.jobs.save(j2, job_id=j2.id, project_id="p1")  # save out of order
    store.jobs.save(j1, job_id=j1.id, project_id="p1")

    history = get_run_history(store, "p1")
    assert [j.id for j in history] == [j1.id, j2.id]


def test_get_past_findings_scoped_by_project(store):
    f1 = Finding(project_id="p1", summary="x", requirement_id="req_1")
    f2 = Finding(project_id="p2", summary="y", requirement_id="req_2")
    store.findings.save(f1, project_id="p1")
    store.findings.save(f2, project_id="p2")

    assert [f.id for f in get_past_findings(store, "p1")] == [f1.id]


def test_prior_findings_by_requirement_keys_by_requirement_id(store):
    finding = Finding(project_id="p1", summary="x", requirement_id="req_1", category=FailureCategory.SECURITY_FINDING)
    store.findings.save(finding, project_id="p1")

    result = prior_findings_by_requirement(store, "p1")
    assert result == {"req_1": finding}


def test_apply_semantic_memory_resolves_matching_unknown(store):
    finding = Finding(
        project_id="p1", summary="Members cannot delete projects. VIOLATED",
        requirement_id="req_1", category=FailureCategory.SECURITY_FINDING, confidence=0.9,
    )
    store.findings.save(finding, project_id="p1")

    req = Requirement(id="req_1", project_id="p1", source_text="Members cannot delete projects.", critical=True)
    unknown = Unknown(project_id="p1", question="q", rationale="No matching endpoint found.", requirement_id="req_1")
    world_model = WorldModel(project_id="p1", requirements=[req], unknowns=[unknown])

    resolved_count = apply_semantic_memory(store, world_model)

    assert resolved_count == 1
    assert unknown.resolved is True
    assert "Resolved from memory" in unknown.rationale
    assert finding.id in unknown.rationale


def test_apply_semantic_memory_leaves_unmatched_unknowns_alone(store):
    unknown = Unknown(project_id="p1", question="q", rationale="No matching endpoint found.", requirement_id="req_no_finding")
    world_model = WorldModel(project_id="p1", requirements=[], unknowns=[unknown])

    resolved_count = apply_semantic_memory(store, world_model)

    assert resolved_count == 0
    assert unknown.resolved is False


def test_get_active_strategy_creates_default_v1_once(store):
    strategy = get_active_strategy(store, "p1")
    assert strategy.version == 1
    assert strategy.weights == DEFAULT_WEIGHTS

    again = get_active_strategy(store, "p1")
    assert again.id == strategy.id  # not recreated on second call


def test_get_active_strategy_returns_highest_version(store):
    from veriforge.domain.models import Strategy

    store.strategies.save(Strategy(project_id="p1", name="default", version=1, weights={}), project_id="p1")
    v2 = Strategy(project_id="p1", name="default", version=2, weights={"coverage": 2.0})
    store.strategies.save(v2, project_id="p1")

    active = get_active_strategy(store, "p1")
    assert active.id == v2.id
