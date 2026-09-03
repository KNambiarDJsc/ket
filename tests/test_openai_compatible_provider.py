import pytest

from veriforge.config import load_dotenv_if_present
from veriforge.llm.openai_compatible_provider import OpenAICompatibleProvider
from veriforge.llm.provider import LLMUnavailableError

load_dotenv_if_present()  # so the live smoke test below picks up ./.env, same as the CLI does


def test_unconfigured_provider_reports_unavailable():
    provider = OpenAICompatibleProvider(model="x", base_url="", api_key="")
    assert provider.is_available() is False


def test_unconfigured_provider_raises_on_generate():
    provider = OpenAICompatibleProvider(model="x", base_url="", api_key="")
    with pytest.raises(LLMUnavailableError):
        provider.generate("hello")


def test_unreachable_host_reports_unavailable():
    provider = OpenAICompatibleProvider(model="x", base_url="http://localhost:19999/v1", api_key="k")
    assert provider.is_available() is False


def test_unreachable_host_raises_on_generate():
    provider = OpenAICompatibleProvider(model="x", base_url="http://localhost:19999/v1", api_key="k")
    with pytest.raises(LLMUnavailableError):
        provider.generate("hello")


def test_headers_include_bearer_token_when_api_key_set():
    provider = OpenAICompatibleProvider(model="x", base_url="http://example", api_key="sk-abc")
    assert provider._headers() == {"Authorization": "Bearer sk-abc"}


def test_headers_empty_when_no_api_key():
    provider = OpenAICompatibleProvider(model="x", base_url="http://example", api_key="")
    assert provider._headers() == {}


def test_env_var_fallbacks(monkeypatch):
    monkeypatch.setenv("VERIFORGE_LLM_MODEL", "env-model")
    monkeypatch.setenv("VERIFORGE_OPENAI_BASE_URL", "http://env-host/v1")
    monkeypatch.setenv("VERIFORGE_OPENAI_API_KEY", "env-key")
    provider = OpenAICompatibleProvider()
    assert provider.model_name == "env-model"
    assert provider._base_url == "http://env-host/v1"
    assert provider._headers() == {"Authorization": "Bearer env-key"}


def test_explicit_args_override_env(monkeypatch):
    monkeypatch.setenv("VERIFORGE_LLM_MODEL", "env-model")
    provider = OpenAICompatibleProvider(model="explicit-model")
    assert provider.model_name == "explicit-model"


def test_live_gx10_endpoint_smoke():
    """Skips unless the real internal endpoint is reachable -- exercises the
    actual configured GX10 proxy when running on a network that can reach it."""
    provider = OpenAICompatibleProvider()
    if not provider.is_available():
        pytest.skip("GX10 OpenAI-compatible endpoint not reachable/configured")
    result = provider.generate("Reply with exactly the word: pong")
    assert isinstance(result, str)
    assert len(result) > 0
