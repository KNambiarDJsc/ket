"""Skill Retriever (spec §40): the piece `docs/PHASES.md` insists on by
name -- "a retriever the Context Compiler calls, not a blob injected into
every context." Every discovered Skill's full body would blow the context
budget if attached unconditionally (exactly the problem progressive
disclosure -- SKILL.md's own prior art -- exists to solve); this scores
each Skill's *description* against the current goal with the same
`keyword_overlap` signal the Context Compiler already uses for
requirements/unknowns, and returns only the top-K matches. A consumer that
actually decides to use a retrieved Skill reads `.body` off the returned
object; nothing here forces every Skill's body into the compiled bundle.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.context.relevance import keyword_overlap
from veriforge.skills.loader import Skill


@dataclass
class ScoredSkill:
    skill: Skill
    score: int


class SkillRetriever:
    def __init__(self, skills: list[Skill]):
        self._skills = skills

    def retrieve(self, goal: str, max_skills: int = 2) -> list[ScoredSkill]:
        scored = [ScoredSkill(skill=s, score=keyword_overlap(goal, s.description)) for s in self._skills]
        # A Skill with zero keyword overlap isn't relevant to this goal --
        # returning it anyway would defeat the entire point of retrieval
        # (every Skill would always show up regardless of the goal).
        relevant = [s for s in scored if s.score > 0]
        relevant.sort(key=lambda s: s.score, reverse=True)
        return relevant[:max_skills]
