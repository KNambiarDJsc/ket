from pathlib import Path

from veriforge.knowledge_graph.graph import KnowledgeGraph, Node, NodeKind
from veriforge.llm.provider import LLMProvider, LLMUnavailableError, NullLLMProvider
from veriforge.retrieval.hybrid import hybrid_search

REPO_SRC = Path(__file__).resolve().parents[1] / "src" / "veriforge"

_VOCAB = ["idempotency", "duplicate", "unrelated"]


class FakeEmbeddingLLM(LLMProvider):
    """A deterministic, bag-of-words "embedding" -- real cosine-similarity
    math exercised against a real, controllable vector space, without
    needing an actual model pulled."""

    def generate(self, prompt, *, system=None):
        raise LLMUnavailableError("not used in this test")

    def is_available(self):
        return True

    @property
    def model_name(self):
        return "fake-embedding"

    def embed(self, text):
        lower = text.lower()
        return [1.0 if word in lower else 0.0 for word in _VOCAB]


class UnavailableEmbeddingLLM(LLMProvider):
    def generate(self, prompt, *, system=None):
        raise LLMUnavailableError("not used")

    def is_available(self):
        return False

    @property
    def model_name(self):
        return "unavailable"
    # embed() left as the base class default -- always raises LLMUnavailableError


def test_hybrid_search_finds_real_matches_with_lexical_score_only():
    results = hybrid_search("idempotency", str(REPO_SRC), llm=NullLLMProvider())

    assert len(results) >= 2
    assert all(r.lexical_score == 1.0 for r in results)
    assert all(r.semantic_score is None for r in results)  # NullLLMProvider.embed() always unavailable
    assert all(r.total_score == 1.0 for r in results)  # no graph, no semantic -- lexical only


def test_hybrid_search_boosts_files_already_in_the_knowledge_graph():
    graph = KnowledgeGraph()
    graph.add_node(Node("file:oracle\\oracle.py", NodeKind.CODE_FILE, "oracle\\oracle.py"))

    results = hybrid_search("idempotency", str(REPO_SRC), graph=graph, llm=NullLLMProvider())

    by_file = {r.file: r for r in results}
    assert by_file["oracle\\oracle.py"].graph_score == 1.0
    assert by_file["oracle\\oracle.py"].total_score > next(
        r.total_score for f, r in by_file.items() if f != "oracle\\oracle.py"
    )


def test_hybrid_search_degrades_gracefully_when_embed_is_unavailable():
    results = hybrid_search("idempotency", str(REPO_SRC), llm=UnavailableEmbeddingLLM())

    assert len(results) >= 2
    assert all(r.semantic_score is None for r in results)


def test_hybrid_search_uses_real_semantic_similarity_when_available():
    results = hybrid_search("idempotency duplicate", str(REPO_SRC), llm=FakeEmbeddingLLM())

    assert all(r.semantic_score is not None for r in results)
    # every match here literally contains "idempotency" or "duplicate" (the search query),
    # so cosine similarity against the query embedding should be strictly positive.
    assert all(r.semantic_score > 0.0 for r in results)
    assert all(r.total_score > 1.0 for r in results)  # lexical (1.0) + real semantic boost


def test_hybrid_search_returns_empty_for_no_lexical_matches():
    results = hybrid_search("this_string_appears_nowhere_xyz123", str(REPO_SRC), llm=NullLLMProvider())
    assert results == []


def test_hybrid_search_results_sorted_highest_score_first():
    graph = KnowledgeGraph()
    graph.add_node(Node("file:oracle\\oracle.py", NodeKind.CODE_FILE, "oracle\\oracle.py"))

    results = hybrid_search("idempotency", str(REPO_SRC), graph=graph, llm=NullLLMProvider())

    scores = [r.total_score for r in results]
    assert scores == sorted(scores, reverse=True)
