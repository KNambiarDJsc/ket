"""Requirement -> structured invariant extraction (spec §5).

Regex/keyword heuristics over the already-classified Requirement.kind, not a
full NLP pipeline — this is honest about its limits (see each extractor's
docstring) but produces machine-checkable structure for the common phrasings
a requirements doc actually uses, which is what the Oracle (Phase 6) and the
Test Scientist (Phase 5) will consume once they exist. A requirement that
doesn't match any pattern gets `structured=None`, not a guessed structure.
"""
from __future__ import annotations

import re

from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import Requirement

_ACTION_VERB_NORMALIZE = {
    "deletes": "delete", "deleting": "delete", "delete": "delete",
    "creates": "create", "creating": "create", "create": "create",
    "edits": "edit", "editing": "edit", "edit": "edit", "updates": "edit", "update": "edit",
    "views": "view", "viewing": "view", "view": "view", "access": "view", "accesses": "view",
    "reads": "view", "read": "view",
}

_NEGATIVE_PATTERN = re.compile(
    r"^(?P<actor>[A-Za-z][\w\s]*?)\s+(?:cannot|can not|may not|must not|shall not|should not)\s+"
    r"(?P<action>\w+)\s+(?P<object>.+?)\.?$",
    re.IGNORECASE,
)
_ONLY_ACTOR_PATTERN = re.compile(
    r"^only\s+(?:an?\s+)?(?P<actor>[\w\s]+?)\s+may\s+(?P<action>\w+)\s+(?P<object>.+?)\.?$",
    re.IGNORECASE,
)
_DURATION_PATTERN = re.compile(
    r"within\s+(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>second|minute|hour)s?", re.IGNORECASE
)
_UNIT_TO_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
_STATUS_CODE_PATTERN = re.compile(r"\b([1-5]\d{2})\b")
_ORDERING_PATTERN = re.compile(
    r"^(?P<earlier>.+?)\s+must\s+(?:exist|happen|occur|be\s+generated)\s+before\s+(?P<later>.+?)\.?$",
    re.IGNORECASE,
)
_STOPWORDS_AFTER_VERB = {"a", "an", "the", "any", "this", "that"}


def _normalize_verb(verb: str) -> str:
    return _ACTION_VERB_NORMALIZE.get(verb.lower(), verb.lower())


def _extract_authorization(text: str) -> dict | None:
    match = _NEGATIVE_PATTERN.match(text)
    if match:
        return {
            "actor": match.group("actor").strip().lower(),
            "action": _normalize_verb(match.group("action")),
            "object": match.group("object").strip(),
            "expected": "denied",
        }
    match = _ONLY_ACTOR_PATTERN.match(text)
    if match:
        return {
            "actor": match.group("actor").strip().lower(),
            "action": _normalize_verb(match.group("action")),
            "object": match.group("object").strip(),
            "expected": "allowed_only_for_this_actor",
        }
    return None


def _extract_temporal(text: str) -> dict | None:
    match = _DURATION_PATTERN.search(text)
    if not match:
        return None
    seconds = float(match.group("num")) * _UNIT_TO_SECONDS[match.group("unit").lower()]
    return {"max_duration_seconds": seconds}


def _infer_action_object_generic(text: str) -> tuple[str, str] | None:
    """Verb-first heuristic: the first recognized action word (in any form
    -- gerund, plain verb), then the next non-stopword word after it as the
    object. Works for "Deleting a project that..." phrasing; deliberately
    NOT attempted for arbitrary prose (e.g. noun-first "Project creation
    must...") -- guessing wrong there is worse than leaving action/object
    unset, per this module's own "don't guess" rule.
    """
    words = [w.strip(".,;:") for w in text.split()]
    for i, word in enumerate(words):
        verb = _ACTION_VERB_NORMALIZE.get(word.lower())
        if verb is None:
            continue
        for candidate in words[i + 1:]:
            lower_candidate = candidate.lower()
            if lower_candidate in _STOPWORDS_AFTER_VERB:
                continue
            if len(candidate) > 2:
                return verb, candidate
            break
        break
    return None


def _extract_data_invariant(text: str) -> dict | None:
    codes = _STATUS_CODE_PATTERN.findall(text)
    if not codes:
        return None
    lower = text.lower()
    if "not" in lower and len(codes) >= 2:
        result = {"expected_status": int(codes[0]), "forbidden_status": int(codes[1])}
    else:
        result = {"expected_status": int(codes[0])}
    action_object = _infer_action_object_generic(text)
    if action_object:
        result["action"], result["object"] = action_object
    return result


def _extract_ordering(text: str) -> dict | None:
    match = _ORDERING_PATTERN.match(text)
    if not match:
        return None
    return {
        "before": match.group("earlier").strip(),
        "after": match.group("later").strip(),
    }


_EXTRACTORS = {
    RequirementKind.NEGATIVE: _extract_authorization,
    RequirementKind.AUTHORIZATION: _extract_authorization,
    RequirementKind.TEMPORAL: _extract_temporal,
    RequirementKind.DATA_INVARIANT: _extract_data_invariant,
    RequirementKind.ORDERING: _extract_ordering,
}


def extract_invariant(requirement: Requirement) -> dict | None:
    extractor = _EXTRACTORS.get(requirement.kind)
    if extractor is None:
        return None
    structured = extractor(requirement.source_text)
    if structured is None:
        # Some requirements carry more than one signal, e.g. "must return a
        # 404, not a 500" classified NEGATIVE by the parser's keyword scan —
        # fall back to a data-invariant pass before giving up.
        structured = _extract_data_invariant(requirement.source_text)
    return structured


def apply_invariants(requirements: list[Requirement]) -> list[Requirement]:
    for req in requirements:
        req.structured = extract_invariant(req)
    return requirements
