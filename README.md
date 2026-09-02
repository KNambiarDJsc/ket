# VeriForge

Autonomous Software Verification & Testing OS. See `docs/PHASES.md` for the
full architecture-to-phase mapping and the prior art (Ralph loop, Anthropic
harness-engineering, EnvHarness, Claude Skills) this design draws from.

This repo currently implements **Phase 0-14** (adds Project persistence/reuse
across runs, episodic/semantic/procedural Memory, evaluation-gated
Learning, two more executable invariant kinds — data-invariant status
checks and the positive "only X may do this" authorization case — two
API/integration-contract invariant kinds (single-endpoint reachability and
a real multi-endpoint create-then-list contract with request/response
schema-consistency checking), a data-integrity invariant kind checked
by reading a real database directly rather than trusting the application's
own API, a Skill System that retrieves versioned procedural knowledge
(`skills/*/SKILL.md`) relevant to the current goal instead of injecting it
all into every context, and a Regression Engine + Test Healer driven by a
real `git diff` signal; running the same `--repo` twice, the second run
recognizes a bug the first run already confirmed, then executes the
*next* candidate and confirms a second, independent bug; see
`docs/PHASES.md` for details): a real, persisted job
lifecycle (parse requirements → statically analyze the repo → explore any
running UI with a real browser → build a world model → rank candidate
experiments → **execute the top one and produce a verdict** → completion
report), driven by a local Ollama model, with every
filesystem/network/LLM/browser/API call routed through a harness (tool
registry + permission tiers + budget enforcement) and a context compiler
that hands a task-scoped slice of the world model to whatever consumes it
next.

Phase 3 adds real AST-based route discovery and a requirements→invariants
engine; Phase 4 adds a real Playwright-driven browser explorer (ARIA
accessibility tree, not raw selectors) that bounded-auto-clicks a live UI
while capturing console/network/screenshots, skipping anything that looks
destructive; Phase 5 adds a Test Scientist that scores every open Unknown
into a ranked candidate Experiment (coverage/novelty/risk/historical-bug-
signal/information-gain/cost/redundancy — spec §12's formula, each axis
backed by a real signal already computed by an earlier phase, not invented);
Phase 6 adds an Executor + Oracle that actually run the highest-ranked
executable experiment against the live app and produce a real PASS/FAIL/
UNCERTAIN verdict backed by an evidence trail (spec §17's Oracle Levels 1
and 3 — HTTP status + state comparison).

Run end-to-end against the bundled example app (which has a minimal HTML
frontend, `GET /ui`, for the explorer to click through), the system: (1)
statically flags the intentionally-planted "members can delete projects"
bug via AST analysis alone, (2) separately discovers the same bug's
"Delete" button live in the browser after creating a project and declines
to auto-click it, (3) ranks "Verify: Members cannot delete projects." as
the single highest-value experiment out of 6 candidates, and (4) actually
executes it — creates a project, deletes it as `role=member`, confirms via
a follow-up GET that it's really gone — and confirms the violation as a
real `SECURITY_FINDING` with a 4-step observation trail as evidence.
Phase 10 adds two more executable invariant kinds — reusing the same
Executor+Oracle pattern — for requirements whose target endpoint(s) are
named directly in the requirement text: "the service must expose a health
check at GET /" (single-endpoint reachability) and "a newly created project
must appear in GET /projects immediately after creation" (a real
multi-endpoint contract: create, then confirm both visibility and
response-schema consistency between the two endpoints). Both already exist
in `examples/requirements.md` and both genuinely PASS against the example
app — a deliberately different outcome from the bugs Phases 6/9 found,
showing the Oracle reports PASS honestly too, not just FAIL.

Phase 11 adds a second bundled app, `examples/example-db-app` (SQLite-
backed instead of an in-memory dict), with a soft-delete bug: its DELETE
endpoint only flags a row `deleted` instead of removing it, and its GET
endpoint filters deleted rows out — so through the API the project
genuinely looks gone. A follow-up API GET (Phase 6's state check) would
report PASS; only a direct `SELECT` against the database (a new
`database.query_sqlite` harness tool) reveals the row is still there,
confirming a real `APPLICATION_BUG` — the concrete case Database
Observation exists for: the application's own API cannot be trusted to
verify its own claims.

Phase 12 adds a Skill System: `skills/*/SKILL.md` files (versioned
frontmatter + a procedural body) documenting how this project's own
Executor/Oracle pairs approach each testing category
(`authorization-testing`, `data-integrity-testing`, `api-contract-testing`
— literally Phases 6/9, 11, and 10's own approaches, written down). A new
`SkillRetriever` scores each Skill's description against the current goal
with the same keyword-overlap signal the Context Compiler already used for
requirements — only the relevant ones' name+description+version get
attached to the compiled context bundle (never a full SKILL.md body
injected regardless of relevance), and every job now writes
`skills-retrieved.json` as a real, run-indexed trail for a future
evaluation phase to eventually judge.

Phase 13 adds a Regression Engine + Test Healer, both driven by a real
`git diff` (`regression/change_impact.py`) — closing two gaps earlier
phases explicitly deferred rather than guessed at: Phase 5's
`change_relevance` scoring axis (a constant placeholder until now) and
Phase 8's documented limitation that a previously-confirmed bug never gets
re-checked even after a fix. Opt in with `--write-regressions`: a
`BUG_VERIFIED` Finding gets a permanent pytest file written into
`--repo`'s own `veriforge_regressions/` directory (never touching
application source), reusing VeriForge's own Executor/Oracle so the file
asserts the fix rather than re-deriving the HTTP sequence from scratch —
verified by actually running the generated file via a real `pytest`
subprocess. Re-running it later, the Test Healer patches the file's
embedded endpoint/base_url if they've drifted, always producing a diff and
refusing outright if the patch would touch the assertion itself.

Phase 14 adds Environment Engineering: `ManagedDockerEnvironment` (build/run/
wait-for-ready/guaranteed-teardown against a real `docker` CLI, degrading
honestly via `docker_available()` when Docker isn't running, exactly like
the local-first Ollama pattern), a `FaultInjectingProxy` (a real HTTP
reverse proxy injecting latency, timeout, deterministic failure-rate,
duplicate delivery, and stale-response replay against a live backend), and
`seed_environment()` (populates a fresh environment with named actors and
resources through the application's own API, not a direct DB insert). All
three are standalone modules, verified independently (a real container
built and run from `examples/example-db-app`'s new `Dockerfile`, all five
fault types measured against a real backend, seeding verified against a
real running app) rather than wired into the CLI yet — that integration
waits for Phase 15's concurrency/security engine to have a real scenario
that needs it.

Everything past that (Security/Concurrency, evaluation lab...) is future
phase work — see `docs/PHASES.md` for the tracker.

## Setup

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # macOS/Linux

ollama pull llama3.2:3b   # or any model you prefer; set via --model
ollama serve              # if not already running

./.venv/Scripts/python -m playwright install chromium   # one-time browser download (~300MB)
```

## Run it

```bash
# Terminal 1: start the example app (dependency-free stdlib server)
./.venv/Scripts/python examples/example-app/app.py

# Terminal 2: run VeriForge against it
./.venv/Scripts/python -m veriforge.cli.main verify \
  --repo examples/example-app \
  --requirements examples/requirements.md \
  --url http://localhost:8000/ui \
  --workdir .
```

This runs the full job lifecycle against the bundled example app (a tiny
dependency-free HTTP server with an intentional authorization bug — members
can delete projects — plus a minimal HTML frontend at `/ui` for the browser
explorer) and writes artifacts (including screenshots, network captures,
and the world model) + a persisted job history under `.veriforge/`. Omit
`--url` to skip browser exploration and only run static analysis.

### Run it against the DB-backed example app (Phase 11)

```bash
# Terminal 1: start the DB-backed example app (dependency-free, uses sqlite3)
./.venv/Scripts/python examples/example-db-app/app.py

# Terminal 2: run VeriForge against it, with --db-path so the data-integrity
# check can actually execute (without it, the requirement stays queued)
./.venv/Scripts/python -m veriforge.cli.main verify \
  --repo examples/example-db-app \
  --requirements examples/db-requirements.md \
  --url http://localhost:8001 \
  --db-path examples/example-db-app/data.db \
  --workdir .
```

This confirms the planted soft-delete bug: the DELETE endpoint only flags a
row `deleted` instead of removing it, so a follow-up API GET alone would
report it gone — only reading the database table directly (via the new
`database.query_sqlite` harness tool) reveals it's still there.

Add `--write-regressions` to also write a permanent regression test for
that confirmed bug into `--repo`'s own `veriforge_regressions/` directory
(Phase 13). Since that writes into whatever `--repo` points at, try it
against a copy of `examples/example-db-app` rather than the tracked one if
you don't want the generated file showing up in `git status`.

## Tests

```bash
./.venv/Scripts/python -m pytest
```

One test (`test_live_ollama_smoke`) exercises the real local Ollama backend
and `tests/test_docker_env.py`'s three tests exercise a real Docker daemon
(building and running an actual container) — both skip gracefully if that
backend isn't reachable. Everything else is hermetic.

## Local-first model policy

Default LLM provider is `veriforge.llm.ollama_provider.OllamaProvider`,
talking to `http://localhost:11434`. Override with `--model` / the
`VERIFORGE_LLM_MODEL` env var, or point `VERIFORGE_OLLAMA_HOST` elsewhere.
`veriforge.llm.provider.LLMProvider` is the abstract interface every future
agent depends on — a hosted-API provider can be dropped in later without
touching orchestration, cartography, or CLI code.
