"""Requirements parser: natural-language markdown -> Requirement objects.

Extracts one Requirement per bullet/numbered line and classifies it with
keyword heuristics (`_classify`). The Phase 3 structuring step
(requirements/invariants.py) turns the classified requirement into a
machine-checkable dict of actor/action/object, duration, status codes, etc.
via regex, not an LLM pass — kept purely deterministic since these patterns
are common, fixed phrasings, not open-ended language understanding.
"""
from __future__ import annotations

import re

from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import Requirement, stable_id

_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")

_NEGATIVE_HINTS = ("cannot", "must not", "shall not", "may not", "should not")
_AUTHZ_HINTS = ("role", "permission", "admin", "member", "owner", "access", "authoriz", "authenticat")
_TEMPORAL_HINTS = ("minute", "second", "hour", "within", "timeout", "sla", "deadline")
_ORDERING_HINTS = ("before", "after", "then", "must exist prior", "must precede")
_SECURITY_HINTS = ("security", "encrypt", "token", "session", "vulnerab", "injection")
_DATA_HINTS = ("unique", "duplicate", "must equal", "must match", "integrity", "consisten")
_STATUS_CODE_RE = re.compile(r"\b[1-5]\d{2}\b")


def _classify(text: str) -> RequirementKind:
    lower = text.lower()
    if any(h in lower for h in _NEGATIVE_HINTS):
        return RequirementKind.NEGATIVE
    if any(h in lower for h in _SECURITY_HINTS):
        return RequirementKind.SECURITY
    if any(h in lower for h in _AUTHZ_HINTS):
        return RequirementKind.AUTHORIZATION
    if any(h in lower for h in _TEMPORAL_HINTS):
        return RequirementKind.TEMPORAL
    if any(h in lower for h in _ORDERING_HINTS):
        return RequirementKind.ORDERING
    if any(h in lower for h in _DATA_HINTS) or _STATUS_CODE_RE.search(text):
        return RequirementKind.DATA_INVARIANT
    if lower.strip():
        return RequirementKind.FUNCTIONAL
    return RequirementKind.UNSPECIFIED


def _is_critical(text: str) -> bool:
    lower = text.lower()
    # "only X may Y" reads as an access-control constraint even without an
    # explicit "must"/"cannot" -- e.g. "Only an owner may delete a project."
    return any(w in lower for w in ("must", "cannot", "shall", "critical", "required", "only"))


def parse_requirements_text(text: str, project_id: str) -> list[Requirement]:
    requirements: list[Requirement] = []
    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if not match:
            continue
        statement = match.group(1).strip()
        if not statement:
            continue
        requirements.append(
            Requirement(
                id=stable_id("req", project_id, statement),
                project_id=project_id,
                source_text=statement,
                kind=_classify(statement),
                critical=_is_critical(statement),
            )
        )
    return requirements


def parse_requirements_file(path: str, project_id: str) -> list[Requirement]:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return parse_requirements_text(text, project_id)
