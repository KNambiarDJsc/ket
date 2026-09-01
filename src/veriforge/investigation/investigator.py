"""Investigator (spec §11/§18): ties Phase 3's static evidence (does the
handler source even reference a role/permission check?), Phase 6's dynamic
evidence (the Oracle's status+state judgment), and Phase 7's reproduction
result into one root-cause narrative -- rather than restating the Oracle's
reasoning alone.
"""
from __future__ import annotations

from veriforge.domain.models import ApiEndpoint
from veriforge.investigation.reproducer import ReproductionResult
from veriforge.oracle.oracle import OracleVerdict


def build_root_cause(
    endpoint: ApiEndpoint,
    verdict: OracleVerdict,
    reproduction: ReproductionResult | None,
) -> str:
    parts = [verdict.reasoning]

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
