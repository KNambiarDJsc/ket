import pytest

from veriforge.llm.ollama_provider import OllamaProvider
from veriforge.llm.provider import LLMUnavailableError


def test_unreachable_host_reports_unavailable():
    provider = OllamaProvider(model="llama3.2:3b", host="http://localhost:19999")
    assert provider.is_available() is False


def test_unreachable_host_raises_on_generate():
    provider = OllamaProvider(model="llama3.2:3b", host="http://localhost:19999")
    with pytest.raises(LLMUnavailableError):
        provider.generate("hello")


def test_live_ollama_smoke():
    """Skips if no local Ollama server is running/pulled -- keeps CI portable
    while still exercising the real local model when this machine has one."""
    provider = OllamaProvider(model="llama3.2:3b")
    if not provider.is_available():
        pytest.skip("Ollama not running locally with llama3.2:3b pulled")
    result = provider.generate("Reply with exactly the word: pong")
    assert isinstance(result, str)
    assert len(result) > 0


# ---- embed() (Phase 18) ----

def test_unreachable_host_raises_on_embed():
    provider = OllamaProvider(model="llama3.2:3b", host="http://localhost:19999")
    with pytest.raises(LLMUnavailableError):
        provider.embed("hello")


def test_live_ollama_embed_smoke():
    """Skips if nomic-embed-text isn't actually pulled on this machine --
    same honest-degradation shape as test_live_ollama_smoke above. Embedding
    and chat models are pulled independently, so this can skip even when
    the chat smoke test above doesn't, and vice versa."""
    provider = OllamaProvider()
    try:
        vector = provider.embed("hello world")
    except LLMUnavailableError:
        pytest.skip("Ollama not running locally with nomic-embed-text pulled")
    assert isinstance(vector, list)
    assert len(vector) > 0
    assert all(isinstance(x, float) for x in vector)
