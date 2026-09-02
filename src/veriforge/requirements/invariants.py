"""Requirement -> structured invariant extraction (spec §5).

Regex/keyword heuristics over the already-classified Requirement.kind, not a
full NLP pipeline — this is honest about its limits (see each extractor's
docstring) but produces machine-checkable structure for the common phrasings
a requirements doc actually uses, which is what the Oracle (Phase 6) and the
Test Scientist (Phase 5) will consume once they exist. A requirement that
doesn't match any pattern gets `structured=None`, not a guessed structure.

Phase 10 adds `_extract_contract`: two API/integration-contract phrasings
("must appear in GET X after creation", "must expose Y at GET Z") whose
target endpoint(s) are named literally in the text, tried as a Kind-
independent fallback alongside the existing data-invariant fallback.

Phase 11 adds `_extract_db_check`: "Deleted X must be removed from the
database" -- a data-integrity requirement no amount of calling the
application's own API can validate, since the point is to catch an API that
lies about having removed something. Reuses the existing action/object
endpoint-matching path rather than inventing a new one.

Phase 15 adds `_extract_concurrency_check`: "A duplicated X-creation request
must not create two X" -- needs Phase 14's FaultInjectingProxy to actually
deliver a request twice at the network layer, plus Phase 11's direct-DB read
to count the resulting rows (an API-only check can't distinguish "one row"
from "two rows with the same reported id" the way a raw SELECT COUNT can).
Tried with *higher* priority than the Kind-based dispatch, not merely as a
fallback like Phase 10/11's shapes: the parser classifies this sentence
NEGATIVE (it contains "must not"), and `_extract_authorization`'s generic
actor/action/object pattern would otherwise also match it -- wrongly, since
"a duplicated project-creation request" is not an actor. Letting the more
specific pattern go first avoids ever producing that wrong structure instead
of catching it after the fact.
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

# Phase 10: API/integration-contract phrasings whose target endpoint(s) are
# named directly in the requirement text -- unlike the authorization/data-
# invariant shapes above, these don't need action/object fuzzy matching
# against discovered endpoints at all, since the method+path is literal.
_CREATION_VISIBLE_PATTERN = re.compile(
    r"(?:a\s+new(?:ly)?\s+created\s+)?(?P<object>[\w\s]+?)\s+must\s+appear\s+in\s+"
    r"(?P<method>GET|POST|PUT|DELETE)\s+(?P<path>\S+?)\s+(?:immediately\s+)?after\s+"
    r"(?:its\s+|the\s+)?creation\.?$",
    re.IGNORECASE,
)
_ENDPOINT_EXPOSURE_PATTERN = re.compile(
    r"must\s+expose\s+(?:a\s+|an\s+)?(?P<label>.+?)\s+at\s+"
    r"(?P<method>GET|POST|PUT|DELETE)\s+(?P<path>\S+?)\.?$",
    re.IGNORECASE,
)

# Phase 11: a data-integrity phrasing that can only be checked by comparing
# the API's story against the database's actual state directly -- unlike
# every prior shape, no amount of calling the application's own API (even a
# follow-up GET) can validate this one, since the bug this targets is
# exactly an API that hides a row without removing it.
_DB_REMOVAL_PATTERN = re.compile(
    r"deleted\s+(?P<object>[\w\s]+?)\s+must\s+(?:be\s+)?(?:actually\s+|permanently\s+)?removed\s+from\s+"
    r"(?:the\s+)?(?:database|storage|db)\b",
    re.IGNORECASE,
)

# Phase 15: "A duplicated project-creation request must not create two
# projects." -- the object is captured from the trailing plural noun ("two
# projects"), not the leading singular compound modifier ("project-
# creation"): the former matches both a discovered endpoint's path and a
# real database table name (both plural), the latter would silently resolve
# to the wrong table ("project" instead of "projects").
_DUPLICATE_CREATION_PATTERN = re.compile(
    r"^a\s+duplicated\s+[\w]+-creation\s+request\s+must\s+not\s+create\s+"
    r"(?:two|more\s+than\s+one|duplicate)\s+(?P<object>\S+?)\.?$",
    re.IGNORECASE,
)


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


def _extract_contract(text: str) -> dict | None:
    """Phase 10: "must appear in GET X ... after creation" (a real
    multi-endpoint contract -- create, then confirm it's visible with
    matching fields elsewhere) and "must expose Y at GET Z" (a single-
    endpoint exposure contract). Tried regardless of how the parser
    classified the sentence (see extract_invariant) since neither phrasing
    hinges on the requirement's Kind -- the first commonly lands as ORDERING
    (it contains "after"), the second as FUNCTIONAL (no other kind's hint
    words apply).
    """
    match = _CREATION_VISIBLE_PATTERN.search(text)
    if match:
        return {
            "contract": "creation_visible_in_listing",
            "object": match.group("object").strip(),
            "method": match.group("method").upper(),
            "path": match.group("path").rstrip(".,;:"),
        }
    match = _ENDPOINT_EXPOSURE_PATTERN.search(text)
    if match:
        return {
            "contract": "endpoint_exposed",
            "label": match.group("label").strip(),
            "method": match.group("method").upper(),
            "path": match.group("path").rstrip(".,;:"),
        }
    return None


def _extract_db_check(text: str) -> dict | None:
    """Phase 11: "Deleted X must be [actually/permanently] removed from the
    database" -- reuses the existing action/object endpoint-matching path
    (ACTION_TO_METHOD/object_keyword in world_model/builder.py) by emitting
    the same "action"/"object" keys the authorization/data-invariant shapes
    use, plus a "db_check" key the Executor/Oracle dispatch on. Tried as a
    Kind-independent fallback like _extract_contract above.
    """
    match = _DB_REMOVAL_PATTERN.search(text)
    if match:
        return {
            "db_check": "removed_after_delete",
            "object": match.group("object").strip(),
            "action": "delete",
        }
    return None


def _extract_concurrency_check(text: str) -> dict | None:
    match = _DUPLICATE_CREATION_PATTERN.match(text)
    if match:
        return {
            "concurrency_check": "no_duplicate_on_creation_replay",
            "object": match.group("object").strip(),
            "action": "create",
        }
    return None


_EXTRACTORS = {
    RequirementKind.NEGATIVE: _extract_authorization,
    RequirementKind.AUTHORIZATION: _extract_authorization,
    RequirementKind.TEMPORAL: _extract_temporal,
    RequirementKind.DATA_INVARIANT: _extract_data_invariant,
    RequirementKind.ORDERING: _extract_ordering,
}


def extract_invariant(requirement: Requirement) -> dict | None:
    # Phase 15, checked first and Kind-independently: this phrasing's own
    # "must not create ..." shape also satisfies the generic NEGATIVE
    # actor/action/object pattern below (the parser classifies it NEGATIVE
    # purely because it contains "must not"), which would otherwise produce
    # a nonsensical authorization structure instead of this one.
    structured = _extract_concurrency_check(requirement.source_text)
    if structured is not None:
        return structured
    extractor = _EXTRACTORS.get(requirement.kind)
    structured = extractor(requirement.source_text) if extractor else None
    if structured is None:
        # Contract phrasings name their own endpoint directly, independent
        # of Kind -- try before giving up (same reasoning as the
        # data-invariant fallback below).
        structured = _extract_contract(requirement.source_text)
    if structured is None:
        # Data-integrity phrasing, also Kind-independent (see
        # _extract_db_check).
        structured = _extract_db_check(requirement.source_text)
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
