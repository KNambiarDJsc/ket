"""Test Healer (Phase 13): fixes a generated regression test's embedded
endpoint/base_url data when the target's routes or base URL have drifted
since the test was generated -- the regression-test analog of a
selector/timing locator fix, scoped to what this project actually owns
(files it generated itself, with a known, deterministic structure) rather
than a generic Playwright selector healer with no real fixture to
validate against.

Two hard rules, both enforced in code, not just by convention:
  1. Never weakens (or even touches) the assertion. `_ASSERTION_MARKER`
     must not appear on any changed line of the diff, or the heal is
     refused outright.
  2. Every heal produces a diff. `HealResult.diff` is populated whenever
     there's a real difference to show, whether or not the heal was
     applied -- a refusal still needs to be inspectable, not silent.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

_ASSERTION_MARKER = "assert result.oracle_verdict.verdict == Verdict.PASS"


@dataclass
class HealResult:
    healed: bool
    diff: str
    new_source: str | None
    reason: str


def heal_regression_test(old_source: str, new_source: str) -> HealResult:
    if old_source == new_source:
        return HealResult(healed=False, diff="", new_source=None, reason="no drift detected")

    old_lines = old_source.splitlines(keepends=True)
    new_lines = new_source.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after"))
    diff_text = "".join(diff_lines)

    touches_assertion = any(
        line.startswith(("+", "-")) and not line.startswith(("+++", "---")) and _ASSERTION_MARKER in line
        for line in diff_lines
    )
    if touches_assertion:
        return HealResult(
            healed=False, diff=diff_text, new_source=None,
            reason="refused: regenerated source would change the assertion itself, not just endpoint/base_url drift",
        )

    return HealResult(
        healed=True, diff=diff_text, new_source=new_source,
        reason="healed: endpoint/base_url drift patched, assertion left untouched",
    )
