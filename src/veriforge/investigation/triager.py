"""Triager (spec §11/§18): classifies a FAIL/UNCERTAIN Oracle verdict into a
FailureCategory with reasoning grounded in the verdict's own confidence and
the requirement's kind -- not a fixed lookup table alone. Low-confidence
verdicts (status and state evidence disagreed) are triaged as
REQUIREMENT_AMBIGUITY rather than confidently blamed on the application.
"""
from __future__ import annotations

from veriforge.domain.enums import FailureCategory, RequirementKind, Verdict
from veriforge.domain.models import Requirement
from veriforge.oracle.oracle import OracleVerdict

_SECURITY_KINDS = {RequirementKind.AUTHORIZATION, RequirementKind.NEGATIVE, RequirementKind.SECURITY}
_LOW_CONFIDENCE_THRESHOLD = 0.7


def triage(verdict: OracleVerdict, requirement: Requirement) -> tuple[FailureCategory, str]:
    if verdict.verdict == Verdict.UNCERTAIN:
        return FailureCategory.REQUIREMENT_AMBIGUITY, (
            f"Oracle could not confidently determine the outcome (confidence={verdict.confidence}): {verdict.reasoning}"
        )
    if verdict.verdict != Verdict.FAIL:
        raise ValueError("triage() is only meaningful for FAIL/UNCERTAIN verdicts")

    if verdict.confidence < _LOW_CONFIDENCE_THRESHOLD:
        return FailureCategory.REQUIREMENT_AMBIGUITY, (
            f"Low-confidence FAIL ({verdict.confidence}) -- status and state evidence disagreed: {verdict.reasoning}"
        )
    if requirement.kind in _SECURITY_KINDS:
        return FailureCategory.SECURITY_FINDING, (
            f"High-confidence violation of a {requirement.kind.value} invariant: {verdict.reasoning}"
        )
    return FailureCategory.APPLICATION_BUG, f"High-confidence violation of a functional invariant: {verdict.reasoning}"
