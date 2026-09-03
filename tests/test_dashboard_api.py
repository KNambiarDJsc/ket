"""Phase 20: the Dashboard API tested against a real job run against the
real example app -- not synthetic Store rows -- so /api/jobs, /api/jobs/
{id}, and /api/jobs/{id}/graph reflect exactly what a real `verify` run
actually persists.
"""
from fastapi.testclient import TestClient

from veriforge.dashboard.api import create_app
from veriforge.events.bus import EventBus
from veriforge.llm.provider import LLMProvider, LLMUnavailableError
from veriforge.orchestrator.run_verify import VerifyParams, run_verify
from veriforge.storage.repository import Store


class NullLLM(LLMProvider):
    def generate(self, prompt, *, system=None):
        raise LLMUnavailableError("no LLM in this test")

    def is_available(self):
        return False

    @property
    def model_name(self):
        return "null"


def _client_with_real_job(store: Store, tmp_path, example_app_server) -> TestClient:
    bus = EventBus(store)
    llm = NullLLM()
    params = VerifyParams(
        repo="examples/example-app", requirements="examples/requirements.md",
        url=example_app_server + "/ui", workdir=str(tmp_path),
    )
    run_verify(params, store=store, bus=bus, llm=llm)
    app = create_app(store=store, bus=bus, llm=llm, workdir=str(tmp_path))
    return TestClient(app)


def test_list_jobs_reflects_a_real_run(store, tmp_path, example_app_server):
    client = _client_with_real_job(store, tmp_path, example_app_server)

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["verdict"] == "FAIL"  # the real, planted authorization bug
    assert jobs[0]["finding_count"] == 1
    assert jobs[0]["project_name"] == "example-app"


def test_job_detail_reflects_real_requirements_and_findings(store, tmp_path, example_app_server):
    client = _client_with_real_job(store, tmp_path, example_app_server)
    job_id = client.get("/api/jobs").json()[0]["id"]

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["job"]["id"] == job_id
    assert len(detail["requirements"]) == 6  # real examples/requirements.md line count
    assert len(detail["findings"]) == 1
    assert "Members cannot delete projects" in detail["findings"][0]["summary"]


def test_job_detail_404_for_unknown_job(store, tmp_path, example_app_server):
    client = _client_with_real_job(store, tmp_path, example_app_server)
    resp = client.get("/api/jobs/job_does_not_exist")
    assert resp.status_code == 404


def test_job_graph_links_the_real_finding_to_its_requirement(store, tmp_path, example_app_server):
    client = _client_with_real_job(store, tmp_path, example_app_server)
    job_id = client.get("/api/jobs").json()[0]["id"]

    resp = client.get(f"/api/jobs/{job_id}/graph")
    assert resp.status_code == 200
    graph = resp.json()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert "REQUIREMENT" in kinds
    assert "FINDING" in kinds
    assert any(e["kind"] == "VIOLATED_BY" for e in graph["edges"])


def test_verify_endpoint_launches_a_real_job(store, tmp_path, example_app_server):
    bus = EventBus(store)
    llm = NullLLM()
    app = create_app(store=store, bus=bus, llm=llm, workdir=str(tmp_path))
    client = TestClient(app)

    resp = client.post("/api/verify", json={
        "repo": "examples/example-app",
        "requirements": "examples/requirements.md",
        "url": example_app_server + "/ui",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FAIL"
    assert body["finding_count"] == 1

    # and it's now visible through the jobs list too
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1


def test_verify_endpoint_rejects_no_target(store, tmp_path):
    bus = EventBus(store)
    llm = NullLLM()
    app = create_app(store=store, bus=bus, llm=llm, workdir=str(tmp_path))
    client = TestClient(app)

    resp = client.post("/api/verify", json={})

    assert resp.status_code == 400


def test_ask_degrades_to_raw_data_when_llm_unavailable(store, tmp_path, example_app_server):
    client = _client_with_real_job(store, tmp_path, example_app_server)

    resp = client.post("/api/ask", json={"question": "any bugs found?"})
    assert resp.status_code == 200
    body = resp.json()
    assert "No LLM is configured" in body["answer"]
    assert len(body["matched_job_ids"]) == 1
