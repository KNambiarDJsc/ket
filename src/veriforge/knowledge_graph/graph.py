"""Software Knowledge Graph (Phase 18): promotes the flat `WorldModel` (plain
lists of Requirement/ApiEndpoint/Unknown) plus the Store's own Finding/
Evidence/Test/Experiment rows into one real, queryable, linked graph --
Requirement → Endpoint → Code, and Requirement → Finding → Evidence /
→ Test, per the spec's own chain.

None of these relationships are new: `world_model.builder.
match_endpoint_for_requirement` already resolves Requirement→Endpoint,
`Finding.requirement_id`/`Evidence.finding_id`/`Experiment.requirement_id`+
`Test.experiment_id` already carry the rest as scattered foreign keys. This
module is what makes them one structure a caller can actually traverse
(`neighbors`, `nodes_of_kind`) instead of independently re-deriving the
same joins every time something needs them.

Deliberately not wired into `JobRunner` yet -- same "standalone, tested
first" precedent as Phase 12's Skill retriever and Phase 14's environment
modules. It's consumed here by `retrieval/hybrid.py`, and is the structure
a future Supervisor-level agent (or a Phase 20 Dashboard) would query
directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from veriforge.domain.models import ApiEndpoint, Evidence, Experiment, Finding, Requirement, Test, WorldModel


class NodeKind(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    ENDPOINT = "ENDPOINT"
    CODE_FILE = "CODE_FILE"
    FINDING = "FINDING"
    EVIDENCE = "EVIDENCE"
    TEST = "TEST"


class EdgeKind(str, Enum):
    MATCHES_ENDPOINT = "MATCHES_ENDPOINT"  # Requirement -> Endpoint
    LOCATED_IN = "LOCATED_IN"              # Endpoint -> CodeFile
    VIOLATED_BY = "VIOLATED_BY"            # Requirement -> Finding
    SUPPORTED_BY = "SUPPORTED_BY"          # Finding -> Evidence
    VERIFIED_BY = "VERIFIED_BY"            # Requirement -> Test


@dataclass
class Node:
    id: str
    kind: NodeKind
    label: str
    data: dict = field(default_factory=dict)


@dataclass
class Edge:
    source_id: str
    target_id: str
    kind: EdgeKind


class KnowledgeGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    def add_node(self, node: Node) -> None:
        self._nodes.setdefault(node.id, node)

    def add_edge(self, edge: Edge) -> None:
        if edge.source_id in self._nodes and edge.target_id in self._nodes:
            self._edges.append(edge)

    @property
    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[Edge]:
        return list(self._edges)

    def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def nodes_of_kind(self, kind: NodeKind) -> list[Node]:
        return [n for n in self._nodes.values() if n.kind == kind]

    def neighbors(self, node_id: str, edge_kind: EdgeKind | None = None, *, direction: str = "out") -> list[Node]:
        """`direction="out"` follows edges where node_id is the source
        (e.g. Requirement -> its Findings); `direction="in"` follows edges
        where node_id is the target (e.g. an Endpoint <- the Requirements
        that matched it)."""
        result: list[Node] = []
        for e in self._edges:
            if edge_kind is not None and e.kind != edge_kind:
                continue
            if direction == "out" and e.source_id == node_id:
                result.append(self._nodes[e.target_id])
            elif direction == "in" and e.target_id == node_id:
                result.append(self._nodes[e.source_id])
        return result


def _endpoint_node_id(endpoint: ApiEndpoint) -> str:
    return f"endpoint:{endpoint.method}:{endpoint.path}"


def build_knowledge_graph(
    world_model: WorldModel,
    *,
    findings: list[Finding] | None = None,
    evidence: list[Evidence] | None = None,
    tests: list[Test] | None = None,
    experiments: list[Experiment] | None = None,
) -> KnowledgeGraph:
    from veriforge.world_model.builder import match_endpoint_for_requirement

    graph = KnowledgeGraph()
    findings = findings or []
    evidence = evidence or []
    tests = tests or []
    experiments = experiments or []

    for req in world_model.requirements:
        graph.add_node(Node(req.id, NodeKind.REQUIREMENT, req.source_text, {
            "kind": req.kind.value, "critical": req.critical,
        }))
        endpoint = match_endpoint_for_requirement(req, world_model.api_endpoints)
        if endpoint is None:
            continue
        ep_id = _endpoint_node_id(endpoint)
        graph.add_node(Node(ep_id, NodeKind.ENDPOINT, f"{endpoint.method} {endpoint.path}", {
            "source_file": endpoint.source_file, "source_line": endpoint.source_line,
        }))
        graph.add_edge(Edge(req.id, ep_id, EdgeKind.MATCHES_ENDPOINT))

        file_id = f"file:{endpoint.source_file}"
        graph.add_node(Node(file_id, NodeKind.CODE_FILE, endpoint.source_file, {}))
        graph.add_edge(Edge(ep_id, file_id, EdgeKind.LOCATED_IN))

    for finding in findings:
        graph.add_node(Node(finding.id, NodeKind.FINDING, finding.summary, {
            "category": finding.category.value, "confidence": finding.confidence,
        }))
        if finding.requirement_id and finding.requirement_id in {r.id for r in world_model.requirements}:
            graph.add_edge(Edge(finding.requirement_id, finding.id, EdgeKind.VIOLATED_BY))

    for ev in evidence:
        graph.add_node(Node(ev.id, NodeKind.EVIDENCE, ev.uri, {"kind": ev.kind}))
        if ev.finding_id:
            graph.add_edge(Edge(ev.finding_id, ev.id, EdgeKind.SUPPORTED_BY))

    requirement_id_by_experiment = {e.id: e.requirement_id for e in experiments}
    for test in tests:
        graph.add_node(Node(test.id, NodeKind.TEST, test.name, {"status": test.status.value}))
        requirement_id = requirement_id_by_experiment.get(test.experiment_id or "")
        if requirement_id and requirement_id in {r.id for r in world_model.requirements}:
            graph.add_edge(Edge(requirement_id, test.id, EdgeKind.VERIFIED_BY))

    return graph
