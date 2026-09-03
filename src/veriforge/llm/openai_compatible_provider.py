"""OpenAI-compatible chat-completions provider.

For hosted/internal endpoints that speak the standard `/v1/chat/completions`
API (LiteLLM proxies, vLLM, and most managed inference gateways all do) --
an alternative to the local-first OllamaProvider (see ollama_provider.py)
for when a team has a shared internal inference endpoint instead of, or in
addition to, a locally pulled model. Implements the same `LLMProvider`
interface, so nothing in the orchestrator/cartographer/etc. needs to know
which one is in use.
"""
from __future__ import annotations

import os

import httpx

from veriforge.llm.provider import LLMProvider, LLMUnavailableError

DEFAULT_MODEL = "gpt-oss-20b"


class OpenAICompatibleProvider(LLMProvider):
    """Model selection order: explicit `model` arg > VERIFORGE_LLM_MODEL env
    var > DEFAULT_MODEL. `base_url` and `api_key` similarly fall back to
    VERIFORGE_OPENAI_BASE_URL / VERIFORGE_OPENAI_API_KEY."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = 120.0,
    ):
        self._model = model or os.environ.get("VERIFORGE_LLM_MODEL", DEFAULT_MODEL)
        # `is None` (not truthiness) for base_url/api_key: an explicitly
        # passed "" must mean "empty", not "fall back to the environment" --
        # unlike `model`, an empty base_url/api_key is a meaningful state a
        # caller (or a test simulating "unconfigured") can legitimately want.
        resolved_base_url = base_url if base_url is not None else os.environ.get("VERIFORGE_OPENAI_BASE_URL", "")
        self._base_url = resolved_base_url.rstrip("/")
        self._api_key = api_key if api_key is not None else os.environ.get("VERIFORGE_OPENAI_API_KEY", "")
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def is_available(self) -> bool:
        if not self._base_url:
            return False
        try:
            resp = httpx.get(f"{self._base_url}/models", headers=self._headers(), timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        if not self._base_url:
            raise LLMUnavailableError("VERIFORGE_OPENAI_BASE_URL is not set")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self._model, "messages": messages}
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload, headers=self._headers(), timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"OpenAI-compatible endpoint at {self._base_url} unreachable or "
                f"rejected the request (model='{self._model}'): {exc}"
            ) from exc
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMUnavailableError(f"No choices in response from {self._base_url}: {data}")
        return choices[0]["message"]["content"] or ""
