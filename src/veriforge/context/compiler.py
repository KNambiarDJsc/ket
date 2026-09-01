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
"""
from __future__ import annotations

from dataclasses import dataclass, field

from veriforge.domain.models import Requirement, Unknown, WorldModel
from veriforge.harness.tools import ToolRegistry


@dataclass
class ToolSummary:
    name: str
    description: str
    risk: str


@dataclass
class ContextBundle:
    goal: str
    relevant_requirements: list[Requirement] = field(default_factory=list)
    relevant_unknowns: list[Unknown] = field(default_factory=list)
    repo_facts: dict = field(default_factory=dict)
    available_tools: list[ToolSummary] = field(default_factory=list)
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

        if self.constraints:
            lines.append(f"CONSTRAINTS: {self.constraints}")

        return "\n".join(lines)


def _keyword_overlap(goal: str, text: str) -> int:
    goal_words = {w.lower() for w in goal.split() if len(w) > 3}
    text_words = {w.lower().strip(".,;:!?") for w in text.split()}
    return len(goal_words & text_words)


class ContextCompiler:
    def compile(
        self,
        world_model: WorldModel,
        goal: str,
        *,
        tool_registry: ToolRegistry | None = None,
        constraints: dict | None = None,
        max_requirements: int = 8,
        max_unknowns: int = 5,
    ) -> ContextBundle:
        ranked_requirements = sorted(
            world_model.requirements,
            key=lambda r: (r.critical, _keyword_overlap(goal, r.source_text)),
            reverse=True,
        )
        selected_requirements = ranked_requirements[:max_requirements]

        ranked_unknowns = sorted(
            world_model.unknowns,
            key=lambda u: _keyword_overlap(goal, u.question),
            reverse=True,
        )
        selected_unknowns = ranked_unknowns[:max_unknowns]

        tools = (
            [ToolSummary(t.name, t.description, t.risk.value) for t in tool_registry.list()]
            if tool_registry
            else []
        )

        return ContextBundle(
            goal=goal,
            relevant_requirements=selected_requirements,
            relevant_unknowns=selected_unknowns,
            repo_facts=world_model.repo_facts,
            available_tools=tools,
            constraints=constraints or {},
            omitted_requirement_count=max(0, len(ranked_requirements) - len(selected_requirements)),
            omitted_unknown_count=max(0, len(ranked_unknowns) - len(selected_unknowns)),
        )
