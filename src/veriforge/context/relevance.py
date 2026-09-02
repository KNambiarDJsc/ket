"""Shared relevance-ranking primitive: keyword overlap between a goal string
and a candidate text. Originally private to the Context Compiler
(requirements/unknowns ranking, Phase 2); promoted to its own module in
Phase 12 so the Skill Retriever can reuse the exact same signal instead of
reinventing a second one.
"""
from __future__ import annotations


def keyword_overlap(goal: str, text: str) -> int:
    goal_words = {w.lower() for w in goal.split() if len(w) > 3}
    text_words = {w.lower().strip(".,;:!?") for w in text.split()}
    return len(goal_words & text_words)
