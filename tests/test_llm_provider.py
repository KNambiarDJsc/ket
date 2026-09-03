import pytest

from veriforge.llm.provider import LLMUnavailableError, NullLLMProvider


def test_embed_default_raises_llm_unavailable():
    """Phase 18: embed() is a non-abstract default on LLMProvider so every
    pre-existing subclass (test doubles included) stays correct without
    implementing it -- confirmed here against the one shipped subclass that
    doesn't override it."""
    with pytest.raises(LLMUnavailableError, match="does not implement embed"):
        NullLLMProvider().embed("anything")
