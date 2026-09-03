from veriforge.domain.enums import FailureCategory, RequirementKind
from veriforge.domain.models import Evidence, Experiment, Finding, Requirement, Test
from veriforge.knowledge_graph.graph import EdgeKind, NodeKind, build_knowledge_graph
from veriforge.world_model.builder import build_world_model

REPO_FACTS = {
    "endpoints": [
        {"method": "DELETE", "path": "/projects/", "source_file": "app.py", "source_line": 97, "mentions_role_check": False},
    ],
}


def _real_world_model():
    req = Requirement(
        project_id="p", source_text="Members cannot delete projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
    )
    return build_world_model("p", [req], REPO_FACTS), req


def test_graph_links_requirement_to_its_matched_endpoint():
    world_model, req = _real_world_model()

    graph = build_knowledge_graph(world_model)

    endpoints = graph.nodes_of_kind(NodeKind.ENDPOINT)
    assert len(endpoints) == 1
    assert endpoints[0].label == "DELETE /projects/"
    assert graph.neighbors(req.id, EdgeKind.MATCHES_ENDPOINT) == endpoints


def test_graph_links_endpoint_to_its_code_file():
    world_model, _req = _real_world_model()

    graph = build_knowledge_graph(world_model)

    endpoint_node = graph.nodes_of_kind(NodeKind.ENDPOINT)[0]
    files = graph.neighbors(endpoint_node.id, EdgeKind.LOCATED_IN)
    assert [f.label for f in files] == ["app.py"]


def test_graph_links_requirement_to_finding_evidence_and_test():
    world_model, req = _real_world_model()
    experiment = Experiment(project_id="p", hypothesis=f"Verify: {req.source_text}", requirement_id=req.id)
    test = Test(project_id="p", experiment_id=experiment.id, name=req.source_text)
    finding = Finding(
        project_id="p", summary="VIOLATED", requirement_id=req.id,
        category=FailureCategory.SECURITY_FINDING, confidence=0.9,
    )
    evidence = Evidence(finding_id=finding.id, kind="api_observation", uri="observation:1")

    graph = build_knowledge_graph(
        world_model, findings=[finding], evidence=[evidence], tests=[test], experiments=[experiment],
    )

    assert [n.id for n in graph.neighbors(req.id, EdgeKind.VIOLATED_BY)] == [finding.id]
    assert [n.id for n in graph.neighbors(req.id, EdgeKind.VERIFIED_BY)] == [test.id]
    assert [n.id for n in graph.neighbors(finding.id, EdgeKind.SUPPORTED_BY)] == [evidence.id]


def test_neighbors_in_direction_finds_requirements_matching_an_endpoint():
    world_model, req = _real_world_model()

    graph = build_knowledge_graph(world_model)

    endpoint_node = graph.nodes_of_kind(NodeKind.ENDPOINT)[0]
    requirements = graph.neighbors(endpoint_node.id, EdgeKind.MATCHES_ENDPOINT, direction="in")
    assert [r.id for r in requirements] == [req.id]


def test_finding_with_no_matching_requirement_produces_no_edge():
    world_model, _req = _real_world_model()
    orphan_finding = Finding(project_id="p", summary="unrelated", requirement_id="req_does_not_exist")

    graph = build_knowledge_graph(world_model, findings=[orphan_finding])

    assert graph.neighbors("req_does_not_exist") == []
    assert orphan_finding.id in {n.id for n in graph.nodes_of_kind(NodeKind.FINDING)}


def test_non_critical_requirement_still_only_produces_a_requirement_node_when_present():
    req = Requirement(project_id="p", source_text="The UI should feel snappy.", critical=False)
    world_model = build_world_model("p", [req], {})

    graph = build_knowledge_graph(world_model)

    assert [n.id for n in graph.nodes_of_kind(NodeKind.REQUIREMENT)] == [req.id]
    assert graph.nodes_of_kind(NodeKind.ENDPOINT) == []
