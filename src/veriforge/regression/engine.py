"""Regression Engine orchestration (Phase 13): ties generation (generator.py)
and healing (healer.py) together into the one entry point `JobRunner` calls
for a `BUG_VERIFIED` Finding -- create the file if it doesn't exist yet;
otherwise regenerate and let the Healer decide whether the difference is
safe drift (apply it, diff visible) or something that would touch the
assertion (refuse, diff still visible for a human to inspect).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.regression.generator import generate_regression_test, regression_test_path
from veriforge.regression.healer import heal_regression_test


@dataclass
class RegressionWriteResult:
    path: Path
    action: str  # "created" | "healed" | "unchanged" | "refused"
    diff: str


def write_or_heal_regression_test(
    *,
    repo_path: str,
    requirement: Requirement,
    action_endpoint: ApiEndpoint,
    all_endpoints: list[ApiEndpoint],
    base_url: str,
) -> RegressionWriteResult:
    new_source = generate_regression_test(
        requirement=requirement, action_endpoint=action_endpoint,
        all_endpoints=all_endpoints, base_url=base_url,
    )
    path = regression_test_path(repo_path, requirement)

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        init_file = path.parent / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")
        path.write_text(new_source, encoding="utf-8")
        return RegressionWriteResult(path=path, action="created", diff="")

    old_source = path.read_text(encoding="utf-8")
    heal_result = heal_regression_test(old_source, new_source)

    if heal_result.healed:
        path.write_text(heal_result.new_source, encoding="utf-8")
        return RegressionWriteResult(path=path, action="healed", diff=heal_result.diff)
    if heal_result.reason == "no drift detected":
        return RegressionWriteResult(path=path, action="unchanged", diff="")
    return RegressionWriteResult(path=path, action="refused", diff=heal_result.diff)
