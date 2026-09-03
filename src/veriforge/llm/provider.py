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

    def embed(self, text: str) -> list[float]:
        """Returns a real embedding vector for `text` (Phase 18: the
        semantic leg of hybrid code retrieval). Not abstract, and not
        implemented here: every existing provider/test-double predates this
        method, and every one of them stayed correct by inheriting this
        honest "unavailable" default rather than being forced to fake a
        vector. Only `OllamaProvider` (via the locally-pulled
        `nomic-embed-text` model docs/PHASES.md has named as reserved for
        this since Phase 2) actually overrides it."""
        raise LLMUnavailableError(f"{self.model_name} does not implement embed()")


class NullLLMProvider(LLMProvider):
    """Always-unavailable provider for harness paths that need an
    LLMProvider instance to satisfy `register_builtin_tools()` but never
    actually call `llm.generate` -- e.g. a Phase 13 generated regression
    test's standalone harness (`regression/runtime.py`), which only ever
    calls api./database. tools."""

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise LLMUnavailableError("NullLLMProvider never generates")

    def is_available(self) -> bool:
        return False

    @property
    def model_name(self) -> str:
        return "null"
