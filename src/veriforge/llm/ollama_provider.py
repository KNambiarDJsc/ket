from __future__ import annotations

import os

import httpx

from veriforge.llm.provider import LLMProvider, LLMUnavailableError

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"


class OllamaProvider(LLMProvider):
    """Local inference via the Ollama HTTP API (no cloud dependency).

    Model selection order: explicit `model` arg > VERIFORGE_LLM_MODEL env var
    > DEFAULT_MODEL. Host similarly via VERIFORGE_OLLAMA_HOST.
    """

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        *,
        timeout: float = 120.0,
    ):
        self._model = model or os.environ.get("VERIFORGE_LLM_MODEL", DEFAULT_MODEL)
        self._host = host or os.environ.get("VERIFORGE_OLLAMA_HOST", DEFAULT_HOST)
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        try:
            resp = httpx.get(f"{self._host}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        try:
            resp = httpx.post(
                f"{self._host}/api/generate", json=payload, timeout=self._timeout
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"Ollama at {self._host} unreachable or model '{self._model}' "
                f"not pulled: {exc}"
            ) from exc
        data = resp.json()
        return data.get("response", "")
