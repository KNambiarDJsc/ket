"""Context Compiler.

Turns the full WorldModel into a small, task-specific bundle. No agent
(present or future) should be handed the entire world model — this is the
one place that decides what's relevant to the current goal, per spec §6.

Phase 2 scope: a straightforward relevance ranking (critical-first, then
keyword overlap with the goal) over requirements/unknowns, plus a compact
tool list (name + one-line description, never full JSON schemas — those
only matter to the executor, not to context budget). Semantic/embedding-
based relevance (using the locally pulled nomic-embed-text model) is a
natural Phase 8 (memory) upgrade, not needed while there's no agent to feed.

Phase 12 adds an optional `skill_retriever`: the same treatment as tools
(name + description only — the "which Skills exist and might be relevant"
index, never a Skill's full body inlined into every bundle regardless of
whether the goal needs it). See `skills/retriever.py` for why that
distinction is the entire point of the Skill System.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from veriforge.context.relevance import keyword_overlap
from veriforge.domain.models import Requirement, Unknown, WorldModel
from veriforge.harness.tools import ToolRegistry
from veriforge.skills.retriever import SkillRetriever


@dataclass
class ToolSummary:
    name: str
    description: str
    risk: str


@dataclass
class SkillSummary:
    name: str
    description: str
    version: int
    score: int


@dataclass
class ContextBundle:
    goal: str
    relevant_requirements: list[Requirement] = field(default_factory=list)
    relevant_unknowns: list[Unknown] = field(default_factory=list)
    repo_facts: dict = field(default_factory=dict)
    available_tools: list[ToolSummary] = field(default_factory=list)
    relevant_skills: list[SkillSummary] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    omitted_requirement_count: int = 0
    omitted_unknown_count: int = 0

    def render_prompt(self) -> str:
        lines = [f"GOAL: {self.goal}", ""]

        if self.relevant_requirements:
            lines.append("RELEVANT REQUIREMENTS:")
            for req in self.relevant_requirements:
                marker = "CRITICAL" if req.critical else req.kind.value
                lines.append(f"  - [{marker}] {req.source_text}")
            if self.omitted_requirement_count:
                lines.append(f"  ... ({self.omitted_requirement_count} more requirements omitted for relevance)")
            lines.append("")

        if self.relevant_unknowns:
            lines.append("OPEN UNKNOWNS:")
            for unk in self.relevant_unknowns:
                lines.append(f"  - {unk.question}")
            if self.omitted_unknown_count:
                lines.append(f"  ... ({self.omitted_unknown_count} more unknowns omitted)")
            lines.append("")

        if self.repo_facts:
            lines.append(f"REPOSITORY FACTS: {self.repo_facts}")
            lines.append("")

        if self.available_tools:
            lines.append("AVAILABLE TOOLS:")
            for tool in self.available_tools:
                lines.append(f"  - {tool.name} [{tool.risk}]: {tool.description}")
            lines.append("")

        if self.relevant_skills:
            lines.append("RELEVANT SKILLS (see SKILL.md for full procedure):")
            for skill in self.relevant_skills:
                lines.append(f"  - {skill.name} (v{skill.version}): {skill.description}")
            lines.append("")

        if self.constraints:
            lines.append(f"CONSTRAINTS: {self.constraints}")

        return "\n".join(lines)


class ContextCompiler:
    def compile(
        self,
        world_model: WorldModel,
        goal: str,
        *,
        tool_registry: ToolRegistry | None = None,
        skill_retriever: SkillRetriever | None = None,
        constraints: dict | None = None,
        max_requirements: int = 8,
        max_unknowns: int = 5,
        max_skills: int = 2,
    ) -> ContextBundle:
        ranked_requirements = sorted(
            world_model.requirements,
            key=lambda r: (r.critical, keyword_overlap(goal, r.source_text)),
            reverse=True,
        )
        selected_requirements = ranked_requirements[:max_requirements]

        ranked_unknowns = sorted(
            world_model.unknowns,
            key=lambda u: keyword_overlap(goal, u.question),
            reverse=True,
        )
        selected_unknowns = ranked_unknowns[:max_unknowns]

        tools = (
            [ToolSummary(t.name, t.description, t.risk.value) for t in tool_registry.list()]
            if tool_registry
            else []
        )

        skills = (
            [
                SkillSummary(scored.skill.name, scored.skill.description, scored.skill.version, scored.score)
                for scored in skill_retriever.retrieve(goal, max_skills=max_skills)
            ]
            if skill_retriever
            else []
        )

        return ContextBundle(
            goal=goal,
            relevant_requirements=selected_requirements,
            relevant_unknowns=selected_unknowns,
            repo_facts=world_model.repo_facts,
            available_tools=tools,
            relevant_skills=skills,
            constraints=constraints or {},
            omitted_requirement_count=max(0, len(ranked_requirements) - len(selected_requirements)),
            omitted_unknown_count=max(0, len(ranked_unknowns) - len(selected_unknowns)),
        )
