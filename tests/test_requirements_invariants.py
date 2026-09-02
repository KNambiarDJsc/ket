from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import Requirement
from veriforge.requirements.invariants import extract_invariant


def req(text, kind):
    return Requirement(project_id="proj_1", source_text=text, kind=kind)


def test_negative_authorization_extracted():
    structured = extract_invariant(req("Members cannot delete projects.", RequirementKind.NEGATIVE))
    assert structured == {
        "actor": "members",
        "action": "delete",
        "object": "projects",
        "expected": "denied",
    }


def test_only_actor_authorization_extracted():
    structured = extract_invariant(req("Only an owner may delete a project.", RequirementKind.AUTHORIZATION))
    assert structured["actor"] == "owner"
    assert structured["action"] == "delete"
    assert structured["expected"] == "allowed_only_for_this_actor"


def test_temporal_duration_extracted_and_normalized_to_seconds():
    structured = extract_invariant(
        req("Project creation must return within 2 seconds.", RequirementKind.TEMPORAL)
    )
    assert structured == {"max_duration_seconds": 2.0}

    structured_minutes = extract_invariant(
        req("Reports must be available within 20 minutes.", RequirementKind.TEMPORAL)
    )
    assert structured_minutes == {"max_duration_seconds": 1200.0}


def test_data_invariant_status_codes_extracted():
    structured = extract_invariant(
        req("Deleting a project that does not exist must return a 404, not a 500.", RequirementKind.DATA_INVARIANT)
    )
    # action/object are inferred (Phase 9) so this can resolve to a concrete
    # endpoint and actually execute, not just be a bare status assertion.
    assert structured == {
        "expected_status": 404, "forbidden_status": 500,
        "action": "delete", "object": "project",
    }


def test_ordering_extracted():
    structured = extract_invariant(
        req("MR must exist before FVR is generated.", RequirementKind.ORDERING)
    )
    assert structured == {"before": "MR", "after": "FVR is generated"}


def test_unmatched_pattern_returns_none():
    structured = extract_invariant(req("The UI should feel snappy.", RequirementKind.FUNCTIONAL))
    assert structured is None


# ---- Phase 10: contract extraction ----

def test_creation_visible_in_listing_extracted():
    # This sentence contains "after" so the parser's own classifier lands it
    # as ORDERING -- _extract_ordering doesn't match "appear ... after", so
    # it falls through to the Kind-independent contract fallback.
    structured = extract_invariant(
        req(
            "A newly created project must appear in GET /projects immediately after creation.",
            RequirementKind.ORDERING,
        )
    )
    assert structured == {
        "contract": "creation_visible_in_listing",
        "object": "project",
        "method": "GET",
        "path": "/projects",
    }


def test_endpoint_exposed_extracted():
    structured = extract_invariant(
        req("The service must expose a health check at GET /.", RequirementKind.FUNCTIONAL)
    )
    assert structured == {
        "contract": "endpoint_exposed",
        "label": "health check",
        "method": "GET",
        "path": "/",
    }


# ---- Phase 11: DB-integrity extraction ----

def test_db_removal_extracted():
    structured = extract_invariant(
        req(
            "Deleted projects must be permanently removed from the database, not merely hidden.",
            RequirementKind.FUNCTIONAL,
        )
    )
    assert structured == {"db_check": "removed_after_delete", "object": "projects", "action": "delete"}


def test_negative_falls_back_to_status_codes_when_no_actor_pattern():
    # e.g. parser classified this NEGATIVE via the word "not", but it's really
    # a data invariant about status codes, not an actor/action sentence.
    structured = extract_invariant(
        req("Deleting a project that does not exist must return a 404, not a 500.", RequirementKind.NEGATIVE)
    )
    assert structured == {
        "expected_status": 404, "forbidden_status": 500,
        "action": "delete", "object": "project",
    }


# ---- Phase 15: request-duplication/concurrency extraction ----

def test_duplicate_creation_extracted():
    structured = extract_invariant(
        req("A duplicated project-creation request must not create two projects.", RequirementKind.NEGATIVE)
    )
    assert structured == {
        "concurrency_check": "no_duplicate_on_creation_replay",
        "object": "projects",
        "action": "create",
    }


def test_duplicate_creation_pattern_takes_priority_over_generic_negative_pattern():
    # The parser classifies this NEGATIVE (it contains "must not"), and the
    # generic actor/action/object NEGATIVE pattern would otherwise also match
    # it -- wrongly, treating "a duplicated project-creation request" as an
    # actor. The concurrency-check pattern must win.
    structured = extract_invariant(
        req("A duplicated project-creation request must not create two projects.", RequirementKind.NEGATIVE)
    )
    assert structured.get("concurrency_check") == "no_duplicate_on_creation_replay"
    assert "actor" not in structured
    assert structured.get("expected") != "denied"
