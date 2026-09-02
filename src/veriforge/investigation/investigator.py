"""Investigator (spec §11/§18): ties Phase 3's static evidence (does the
handler source even reference a role/permission check?), Phase 6's dynamic
evidence (the Oracle's status+state judgment), and Phase 7's reproduction
result into one root-cause narrative -- rather than restating the Oracle's
reasoning alone.

Phase 10/11 introduced Finding-producing requirement kinds that aren't
about authorization at all (API contracts, DB-integrity checks) -- for
those, commenting on role/permission-check presence would be a non-sequitur
grafted onto an unrelated bug. `build_root_cause` takes the originating
`Requirement` (optional, defaulting to the old always-comment behavior for
existing callers) and only includes the role-check note when the
requirement's kind actually makes it a relevant signal.

Phase 15's duplicate-creation requirement is a real gap in that scheme: its
phrasing ("...must not create two projects.") gets classified NEGATIVE by
the parser purely because it contains "must not", which *is* one of the
kinds treated as role-check-relevant below -- but the finding has nothing to
do with role/permission checks at all. `build_root_cause` also excludes it
by checking `structured["concurrency_check"]` directly rather than trusting
Kind alone, the same lesson Phase 11's `db_check` exclusion could only
half-teach (it worked there only because that requirement happened to
classify FUNCTIONAL, not because anything checked its structured shape).
"""
from __future__ import annotations

from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.investigation.reproducer import ReproductionResult
from veriforge.oracle.oracle import OracleVerdict

_ROLE_CHECK_RELEVANT_KINDS = {RequirementKind.AUTHORIZATION, RequirementKind.NEGATIVE, RequirementKind.SECURITY}


def build_root_cause(
    endpoint: ApiEndpoint,
    verdict: OracleVerdict,
    reproduction: ReproductionResult | None,
    requirement: Requirement | None = None,
) -> str:
    parts = [verdict.reasoning]

    is_concurrency_shaped = bool(
        requirement is not None
        and requirement.structured
        and requirement.structured.get("concurrency_check")
    )
    role_check_relevant = requirement is None or (
        requirement.kind in _ROLE_CHECK_RELEVANT_KINDS and not is_concurrency_shaped
    )
    if role_check_relevant:
        if not endpoint.mentions_role_check:
            parts.append(
                f"Static analysis of {endpoint.source_file}:{endpoint.source_line} found no "
                "role/permission-check identifier in the handler source, consistent with the observed behavior."
            )
        else:
            parts.append(
                f"Note: {endpoint.source_file}:{endpoint.source_line} DOES reference a role/permission-looking "
                "identifier, yet the check still failed -- the identifier may be unused or misapplied; needs code review."
            )

    if reproduction is not None:
        parts.append(
            "Reproduced on a second independent run -- consistent result, not flaky."
            if reproduction.reproducible
            else "NOT reproduced on a second run -- results were inconsistent; treat as possibly flaky, not confirmed."
        )

    return " ".join(parts)
