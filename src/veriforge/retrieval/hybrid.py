"""Hybrid Retrieval (Phase 18, spec: "hybrid lexical+semantic+graph
retrieval"): ranks code locations relevant to a query by combining three
independent signals instead of trusting any one alone --

  lexical  -- does the line literally contain the query text
              (code_intelligence.symbols.search_code).
  graph    -- is this file already connected to a Requirement/Finding the
              Knowledge Graph knows about (knowledge_graph.graph) -- a line
              this project has already investigated is a stronger match
              than one that only happens to share a word.
  semantic -- real embedding cosine similarity (LLMProvider.embed), when a
              provider actually implements it. Every match without a
              working embedding model still ranks correctly on the other
              two signals -- semantic is additive, never load-bearing, the
              same local-first degradation this project applies to every
              optional capability (no Ollama, no Docker, no git).

Deliberately not wired into `context.compiler.ContextCompiler` yet -- that
compiler's job is picking relevant *requirements/unknowns/skills* for an
LLM-driven agent step, which doesn't exist in this fully deterministic
pipeline yet (see job_runner.py's own comment on why Skill-version
correlation is still an open hook). This is the retrieval primitive that
integration would eventually call.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from veriforge.code_intelligence.symbols import search_code
from veriforge.knowledge_graph.graph import KnowledgeGraph, NodeKind
from veriforge.llm.provider import LLMProvider, LLMUnavailableError

# Bounds how many real embedding calls one search can make, independent of
# how many lexical candidates matched -- semantic scoring is a real network
# round trip per call, and this is additive signal, not the primary one.
_MAX_SEMANTIC_CALLS = 15


@dataclass
class RankedMatch:
    file: str
    lineno: int
    line: str
    lexical_score: float
    graph_score: float
    semantic_score: float | None  # None when no embedding model was available
    total_score: float


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def hybrid_search(
    query: str,
    repo_path: str,
    *,
    graph: KnowledgeGraph | None = None,
    llm: LLMProvider | None = None,
    max_results: int = 20,
) -> list[RankedMatch]:
    matches = search_code(repo_path, query, max_results=max_results)
    if not matches:
        return []

    graph_files = {n.label for n in graph.nodes_of_kind(NodeKind.CODE_FILE)} if graph is not None else set()

    query_embedding: list[float] | None = None
    if llm is not None:
        try:
            query_embedding = llm.embed(query)
        except LLMUnavailableError:
            query_embedding = None

    ranked: list[RankedMatch] = []
    for i, m in enumerate(matches):
        graph_score = 1.0 if m.file in graph_files else 0.0
        semantic_score = None
        if query_embedding is not None and i < _MAX_SEMANTIC_CALLS:
            try:
                semantic_score = _cosine(query_embedding, llm.embed(m.line))
            except LLMUnavailableError:
                semantic_score = None
        total = 1.0 + graph_score + (semantic_score or 0.0)  # lexical_score is always 1.0: search_code already guarantees a literal match
        ranked.append(RankedMatch(m.file, m.lineno, m.line, 1.0, graph_score, semantic_score, total))

    ranked.sort(key=lambda r: r.total_score, reverse=True)
    return ranked
