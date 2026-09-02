"""Oracle (spec §17): compares expected vs. observed and emits a verdict.

`judge_authorization` (Phase 6) implements Level 1 (exact assertion — was
the HTTP status a 401/403 denial or a 2xx success?) combined with Level 3
(state comparison — did the resource actually still exist afterward?) when
a state check was possible. State comparison is the primary signal when
both are available, since a status code alone can lie (e.g. a handler that
returns 200 but silently no-ops); agreement between the two raises
confidence, disagreement lowers it rather than being silently ignored.

Phase 9 adds two more judgments: `judge_data_invariant` (Level 1 only — an
exact expected/forbidden HTTP status assertion) and
`judge_allowed_only_for_actor` (the positive-authorization counterpart to
`judge_authorization`: the named actor must succeed *and* a different role
must be denied, or it isn't actually exclusive).

Phase 10 adds `judge_endpoint_exposure` (Level 1 — is the declared endpoint
actually reachable?) and `judge_creation_visibility` (a real multi-endpoint
contract judgment: did the created resource show up in the listing endpoint
at all, and if so, do its fields still match the creation response? — a
schema-consistency check, not just a presence check).

Phase 11 adds `judge_db_removal`: a genuine Level 3 upgrade over
`judge_authorization`'s state check. That one confirms "gone" via a
follow-up API GET, which only proves what the application is willing to
report; this one reads the database row directly, so it can catch an
application that hides a row from its own API without actually deleting it
— a bug Phase 6's API-only state check cannot see by construction.

Temporal and true cross-service workflows still have no Oracle
implementation — Phase 9/10/11 only execute what they can honestly judge;
everything else stays unexecuted (see execution/http_executor.py,
execution/db_executor.py, and execution/experiment_runner.is_executable).

Phase 15 adds `judge_duplicate_creation`: a real database row count is the
only honest ground truth here — an API response alone can't distinguish "one
resource created" from "two resources created, one response discarded by a
flaky network" (exactly what Phase 14's FaultInjectingProxy's duplicate_paths
simulates). Judged purely on the row-count delta, not on any HTTP status.
"""
from __future__ import annotations

from dataclasses import dataclass

from veriforge.domain.enums import Verdict

_DENIAL_STATUSES = (401, 403)


@dataclass
class OracleVerdict:
    verdict: Verdict
    confidence: float
    expected: str
    observed: str
    reasoning: str


def judge_authorization(
    expected: str,
    response_status: int,
    resource_still_present: bool | None,
) -> OracleVerdict:
    status_says_denied = response_status in _DENIAL_STATUSES
    status_says_allowed = 200 <= response_status < 300

    if resource_still_present is not None:
        observed = "denied" if resource_still_present else "allowed"
        status_agrees = status_says_denied if observed == "denied" else status_says_allowed
        confidence = 0.9 if status_agrees else 0.7
        state_note = f"resource_still_present={resource_still_present} (checked via follow-up GET)"
    elif status_says_denied:
        observed = "denied"
        confidence = 0.6
        state_note = "no state check available; judged from HTTP status alone"
    elif status_says_allowed:
        observed = "allowed"
        confidence = 0.6
        state_note = "no state check available; judged from HTTP status alone"
    else:
        return OracleVerdict(
            verdict=Verdict.UNCERTAIN,
            confidence=0.3,
            expected=expected,
            observed="unknown",
            reasoning=(
                f"Response status {response_status} is neither a clear denial (401/403) "
                "nor a clear success (2xx); cannot determine whether the action was denied."
            ),
        )

    reasoning = (
        f"Requirement expects '{expected}'. Observed '{observed}' "
        f"(status={response_status}, {state_note})."
    )
    if observed == expected:
        return OracleVerdict(Verdict.PASS, confidence, expected, observed, reasoning)
    return OracleVerdict(
        Verdict.FAIL,
        confidence,
        expected,
        observed,
        reasoning + " The action was not actually denied — this violates the requirement.",
    )


def judge_data_invariant(
    expected_status: int,
    forbidden_status: int | None,
    response_status: int,
) -> OracleVerdict:
    if response_status == expected_status:
        return OracleVerdict(
            Verdict.PASS, 0.9, str(expected_status), str(response_status),
            f"Got the expected status {expected_status}.",
        )
    if forbidden_status is not None and response_status == forbidden_status:
        return OracleVerdict(
            Verdict.FAIL, 0.9, str(expected_status), str(response_status),
            f"Got the explicitly forbidden status {forbidden_status} instead of {expected_status} "
            "— this violates the requirement.",
        )
    return OracleVerdict(
        Verdict.UNCERTAIN, 0.4, str(expected_status), str(response_status),
        f"Got status {response_status}, which is neither the expected {expected_status} "
        f"nor the forbidden {forbidden_status}; cannot judge this against the requirement as stated.",
    )


def judge_allowed_only_for_actor(
    actor_status: int,
    actor_resource_gone: bool,
    other_status: int,
    other_resource_gone: bool,
) -> OracleVerdict:
    actor_succeeded = 200 <= actor_status < 300 and actor_resource_gone
    if not actor_succeeded:
        return OracleVerdict(
            Verdict.UNCERTAIN, 0.4, "allowed_only_for_this_actor", "actor_denied_or_unclear",
            f"Could not confirm the named actor can even perform the action (status={actor_status}, "
            f"resource_gone={actor_resource_gone}); cannot judge exclusivity without that baseline.",
        )
    other_succeeded = 200 <= other_status < 300 and other_resource_gone
    if other_succeeded:
        return OracleVerdict(
            Verdict.FAIL, 0.85, "allowed_only_for_this_actor", "allowed_for_others_too",
            f"The named actor could perform the action, as expected, but so could a different role "
            f"(status={other_status}, resource_gone={other_resource_gone}) — this is not actually "
            "exclusive to that actor, which violates the requirement.",
        )
    return OracleVerdict(
        Verdict.PASS, 0.85, "allowed_only_for_this_actor", "allowed_only_for_actor",
        f"The named actor could perform the action; a different role was denied (status={other_status}).",
    )


def judge_endpoint_exposure(expected_method: str, expected_path: str, response_status: int) -> OracleVerdict:
    if 200 <= response_status < 400:
        return OracleVerdict(
            Verdict.PASS, 0.9, "reachable (2xx/3xx)", str(response_status),
            f"{expected_method} {expected_path} answered with {response_status}, "
            "as the requirement expects it to be exposed.",
        )
    return OracleVerdict(
        Verdict.FAIL, 0.85, "reachable (2xx/3xx)", str(response_status),
        f"{expected_method} {expected_path} answered with {response_status} instead of a reachable status "
        "— this violates the requirement that this endpoint must be exposed.",
    )


def judge_db_removal(row_still_in_db: bool) -> OracleVerdict:
    if row_still_in_db:
        return OracleVerdict(
            Verdict.FAIL, 0.9, "not present in the database", "still present in the database",
            "The API reported the resource as deleted, but a direct database read shows the row is "
            "still physically present — this violates the requirement, and a follow-up API GET alone "
            "would not have caught it (the application itself hides the row from that endpoint).",
        )
    return OracleVerdict(
        Verdict.PASS, 0.9, "not present in the database", "not present in the database",
        "A direct database read confirms the row was actually removed, not just hidden from the API.",
    )


def judge_creation_visibility(listing_entry: dict | None, schema_mismatches: list[str]) -> OracleVerdict:
    if listing_entry is None:
        return OracleVerdict(
            Verdict.FAIL, 0.85, "visible in the listing with matching fields", "not_found_in_listing",
            "The newly created resource did not appear in the listing endpoint's response at all "
            "— this violates the requirement.",
        )
    if schema_mismatches:
        return OracleVerdict(
            Verdict.FAIL, 0.8, "visible in the listing with matching fields", "schema_mismatch",
            "The resource appeared in the listing, but its fields don't match the creation response: "
            + "; ".join(schema_mismatches),
        )
    return OracleVerdict(
        Verdict.PASS, 0.9, "visible in the listing with matching fields", "consistent",
        "The newly created resource appeared in the listing endpoint's response with fields matching "
        "the creation response.",
    )


def judge_duplicate_creation(row_count_delta: int) -> OracleVerdict:
    if row_count_delta == 1:
        return OracleVerdict(
            Verdict.PASS, 0.9, "exactly one row created", "1 row created",
            "The table's row count increased by exactly one despite the creation request being "
            "delivered to the backend twice — the endpoint is idempotent under duplicated delivery.",
        )
    if row_count_delta > 1:
        return OracleVerdict(
            Verdict.FAIL, 0.9, "exactly one row created", f"{row_count_delta} rows created",
            f"The table's row count increased by {row_count_delta} after a single client request was "
            "delivered to the backend twice — the endpoint has no idempotency protection, so a "
            "duplicated/retried network request silently creates duplicate resources. This violates "
            "the requirement.",
        )
    return OracleVerdict(
        Verdict.UNCERTAIN, 0.3, "exactly one row created", f"{row_count_delta} rows created",
        f"The table's row count changed by {row_count_delta} (expected exactly 1); this doesn't clearly "
        "confirm or rule out a duplicate-creation vulnerability.",
    )
