import os
import subprocess

from veriforge.domain.enums import FailureCategory
from veriforge.domain.models import ApiEndpoint, Finding, Job, Requirement, Unknown, WorldModel
from veriforge.memory.episodic import get_past_findings, get_run_history
from veriforge.memory.procedural import get_active_strategy
from veriforge.memory.semantic import apply_semantic_memory, prior_findings_by_requirement
from veriforge.strategist.scientist import DEFAULT_WEIGHTS

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _git(repo_path, *args):
    subprocess.run(["git", *args], cwd=repo_path, check=True, capture_output=True, text=True, env=_GIT_ENV)


def _commit(repo_path, content):
    (repo_path / "app.py").write_text(content, encoding="utf-8")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-q", "-m", "change")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True, check=True)
    return result.stdout.strip()


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


# ---- Phase 13: change-aware reopening ----

def _authz_world_model():
    endpoint = ApiEndpoint(project_id="p1", method="DELETE", path="/projects/", source_file="app.py", source_line=1)
    req = Requirement(
        id="req_1", project_id="p1", source_text="Members cannot delete projects.", critical=True,
        structured={"actor": "members", "action": "delete", "object": "projects", "expected": "denied"},
    )
    unknown = Unknown(project_id="p1", question="q", rationale="Matched to DELETE /projects/.", requirement_id="req_1")
    return WorldModel(project_id="p1", requirements=[req], unknowns=[unknown], api_endpoints=[endpoint]), unknown


def test_apply_semantic_memory_reopens_when_backing_file_changed(store, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    old_commit = _commit(repo, "v1\n")

    prior_job = Job(project_id="p1", repo_path=str(repo), repo_commit=old_commit)
    store.jobs.save(prior_job, job_id=prior_job.id, project_id="p1")

    finding = Finding(
        project_id="p1", summary="VIOLATED", requirement_id="req_1",
        category=FailureCategory.SECURITY_FINDING, confidence=0.9, job_id=prior_job.id,
    )
    store.findings.save(finding, project_id="p1")

    new_commit = _commit(repo, "v2 -- app.py actually changed\n")
    current_job = Job(project_id="p1", repo_path=str(repo), repo_commit=new_commit)

    world_model, unknown = _authz_world_model()
    resolved_count = apply_semantic_memory(store, world_model, current_job=current_job)

    assert resolved_count == 0
    assert unknown.resolved is False
    assert "re-verifying" in unknown.rationale
    assert finding.id in unknown.rationale


def test_apply_semantic_memory_still_resolves_when_nothing_changed(store, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    commit = _commit(repo, "v1\n")

    prior_job = Job(project_id="p1", repo_path=str(repo), repo_commit=commit)
    store.jobs.save(prior_job, job_id=prior_job.id, project_id="p1")

    finding = Finding(
        project_id="p1", summary="VIOLATED", requirement_id="req_1",
        category=FailureCategory.SECURITY_FINDING, confidence=0.9, job_id=prior_job.id,
    )
    store.findings.save(finding, project_id="p1")

    current_job = Job(project_id="p1", repo_path=str(repo), repo_commit=commit)  # same commit -- nothing changed

    world_model, unknown = _authz_world_model()
    resolved_count = apply_semantic_memory(store, world_model, current_job=current_job)

    assert resolved_count == 1
    assert unknown.resolved is True


def test_apply_semantic_memory_without_current_job_keeps_phase_8_behavior(store):
    finding = Finding(
        project_id="p1", summary="VIOLATED", requirement_id="req_1",
        category=FailureCategory.SECURITY_FINDING, confidence=0.9,
    )
    store.findings.save(finding, project_id="p1")

    world_model, unknown = _authz_world_model()
    resolved_count = apply_semantic_memory(store, world_model)

    assert resolved_count == 1
    assert unknown.resolved is True


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
