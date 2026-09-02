"""Evaluation Lab ground truth (Phase 16, spec §42): known, seeded bugs and
known-good requirements across this project's own example apps, so the
Harness Auditor can measure real precision/recall instead of asserting
"found a bug" with no way to tell a true one from a false alarm.

Every entry here is a claim verifiable by construction, not a guess: each
bug was planted deliberately (Phases 6/9/11/15) and each PASS was confirmed
live against the running app when its phase was built (Phases 10/11/14) --
see each GroundTruthRequirement's `note` for exactly which phase and why.
A requirement with no Executor/Oracle yet (temporal, ordering) is recorded
with `expected_verdict=None` -- not scored, since nothing executes it --
rather than silently dropped, so the manifest stays an honest count of how
much of a requirements file can actually be checked today.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veriforge.domain.enums import Verdict

_REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = _REPO_ROOT / "examples"


@dataclass
class GroundTruthRequirement:
    source_text: str
    expected_verdict: Verdict | None  # None == not yet executable; excluded from scoring
    note: str


@dataclass
class Benchmark:
    name: str
    repo_path: Path
    requirements_path: Path
    app_module_path: Path
    needs_db: bool
    ground_truth: list[GroundTruthRequirement]


EXAMPLE_APP = Benchmark(
    name="example-app",
    repo_path=EXAMPLES_DIR / "example-app",
    requirements_path=EXAMPLES_DIR / "requirements.md",
    app_module_path=EXAMPLES_DIR / "example-app" / "app.py",
    needs_db=False,
    ground_truth=[
        GroundTruthRequirement(
            "Members cannot delete projects.", Verdict.FAIL,
            "Phase 6: DELETE /projects/<id> never checks X-Role -- a member can delete just fine.",
        ),
        GroundTruthRequirement(
            "Only an owner may delete a project.", Verdict.FAIL,
            "Phase 9: the app has no role differentiation at all -- a synthesized not-owner role "
            "deletes just as easily as owner, so it isn't actually exclusive.",
        ),
        GroundTruthRequirement(
            "Project creation must return within 2 seconds.", None,
            "Temporal invariant -- no Executor/Oracle exists for this shape yet (see Phase 9 notes' "
            "explicit deferral); excluded from scoring rather than guessed at.",
        ),
        GroundTruthRequirement(
            "A newly created project must appear in GET /projects immediately after creation.", Verdict.PASS,
            "Phase 10: the app is synchronous and single-process -- a POST really is visible in the "
            "very next GET, with matching fields.",
        ),
        GroundTruthRequirement(
            "Deleting a project that does not exist must return a 404, not a 500.", Verdict.PASS,
            "app.py's do_DELETE guards with `if project_id in PROJECTS`, so an unknown id correctly "
            "gets a 404, never a 500.",
        ),
        GroundTruthRequirement(
            "The service must expose a health check at GET /.", Verdict.PASS,
            "GET / answers 200 with a status payload.",
        ),
    ],
)

EXAMPLE_DB_APP = Benchmark(
    name="example-db-app",
    repo_path=EXAMPLES_DIR / "example-db-app",
    requirements_path=EXAMPLES_DIR / "db-requirements.md",
    app_module_path=EXAMPLES_DIR / "example-db-app" / "app.py",
    needs_db=True,
    ground_truth=[
        GroundTruthRequirement(
            "Deleted projects must be permanently removed from the database, not merely hidden.", Verdict.FAIL,
            "Phase 11: DELETE only ever sets deleted=1 -- the row is still physically present, "
            "hidden from the API's own GET but not actually gone.",
        ),
        GroundTruthRequirement(
            "The service must expose a health check at GET /.", Verdict.PASS,
            "GET / answers 200 with a status payload.",
        ),
        GroundTruthRequirement(
            "A duplicated project-creation request must not create two projects.", Verdict.FAIL,
            "Phase 15: no idempotency key at all -- a request delivered twice at the network layer "
            "genuinely creates two rows.",
        ),
    ],
)

ALL_BENCHMARKS: list[Benchmark] = [EXAMPLE_APP, EXAMPLE_DB_APP]
