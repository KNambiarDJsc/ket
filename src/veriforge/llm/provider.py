"""Model-agnostic LLM provider interface.

Nothing in the orchestrator, cartographer, or (later) agents should import a
concrete provider directly — they take an `LLMProvider` and call `.generate`.
Ollama is the default, local implementation (see ollama_provider.py); a
hosted-API provider can be added later by implementing this same interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMUnavailableError(RuntimeError):
    """Raised when the provider cannot reach its backend (e.g. Ollama not running)."""


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a single completion for `prompt`. Raises LLMUnavailableError
        if the backend cannot be reached."""

    @abstractmethod
    def is_available(self) -> bool:
        """Best-effort, cheap check that the backend is reachable."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...
