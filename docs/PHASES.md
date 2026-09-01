# VeriForge — Build Phases & Prior Art

## Prior art this design draws from

- **Ralph loop** (Geoffrey Huntley, "Ralph Wiggum as a Software Engineer") — the
  primitive of a durable, single-purpose agent loop that re-reads its own state
  from disk each iteration instead of carrying a growing conversation. VeriForge's
  loop engine is Ralph *plus* an explicit reason-to-continue check per iteration
  (§10 of the spec) so it doesn't blindly re-run.
- **Anthropic — "Effective context engineering for AI agents" / agentic harness
  engineering writeups** — context compaction vs. reset, structured hand-off
  artifacts between sessions, generator/evaluator separation, permission tiers
  by risk. Mirrored in the Context Engine (§6), Harness Engine (§7), and
  Principle 4 (never self-evaluate).
- **Anthropic multi-agent researcher pattern** (subagents communicate through
  artifacts, not shared transcript) — mirrored in §10 (Explorer → exploration.json
  → Strategist → hypotheses.json → ...).
- **Google Research EnvHarness** — the environment itself is a controllable,
  mutable subject (fault injection, clock control, seeded state), not just a
  fixed target. Mirrored in Environment Engineering (§9/§22).
- **Claude Code / Claude Agent SDK Skills (SKILL.md)** — progressive disclosure
  of procedural knowledge instead of a bloated system prompt; skills as
  versioned, evaluable, composable units. Mirrored in §40 (Skill System).

None of these are dependencies to import — they're the shape of the design.
VeriForge's own interfaces (harness, loop, world model, oracle) are what's load
bearing; the model behind it (Ollama locally, or a hosted API later) is a
swappable implementation detail behind `llm.provider.LLMProvider`.

## Phase plan (as-built tracker)

Phases 0–7 (below) are done and form one real, verified vertical slice:
parse → statically analyze → explore → rank hypotheses → execute → verify →
triage/reproduce/root-cause. Phases 8+ were re-scoped in a 2026-09-01 planning
pass against a much larger production-platform spec (GitHub App source
connectors, a persistent Software Knowledge Graph, Skill System, Memory/
Learning, Environment Engineering, Security/Concurrency, Healer/Fixer/
Regression, Evaluation Lab/Harness Auditor, and a full web Dashboard). That
spec is **not** being built as one giant leap — see "2026-09-01 scope
reconciliation" below for how it maps onto this phase list and what's
explicitly deferred.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold, packaging, tooling | ✅ |
| 1 | Domain models, event model, job state machine, SQLite persistence, CLI, local LLM provider (Ollama) | ✅ |
| 2 | Harness: tool registry, permission tiers, budgets, context compiler | ✅ |
| 3 | Repository cartographer (AST-based routes/persistence) + requirements→invariants → richer world model | ✅ |
| 4 | Browser explorer (Playwright/DOM/ARIA/network/console) | ✅ |
| 5 | Test Scientist: hypothesis generation + active experiment scoring | ✅ |
| 6 | Executor + Oracle (levels 1–7) + evidence | ✅ (levels 1 & 3 only, one invariant kind — see notes) |
| 7 | Triager, Investigator, Reproducer | ✅ |
| 8 | **Project persistence/reuse + Memory** (episodic/semantic/procedural) **+ evaluation-gated Learning** — a Strategy's scoring weights persist per project and only get "kept" once measurably better across enough runs; a prior run's confirmed Finding marks its Unknown resolved so later runs don't re-flag it | ✅ |
| 9 | **Broaden Oracle/Executor invariant coverage**: data-invariant (expected/forbidden status) and the positive `"allowed_only_for_this_actor"` case are now executable alongside `expected=="denied"`. Temporal and ordering remain unexecuted (see notes) | ✅ |
| 10 | **API/Integration/System testing breadth**: multi-endpoint contract checks, request/response schema assertions, service-to-service workflows (not just one endpoint in isolation). Covers Core: API, integration, system testing | not started |
| 11 | **Database Observation**: a real DB-backed example app + DB state-comparison oracle (Level 3 today only checks via a follow-up GET; needs a real adapter for SQL/NoSQL state checks). Covers Core: data integrity | not started |
| 12 | **Skill System**: `skills/*/SKILL.md` as versioned, evaluable procedural knowledge; a retriever the Context Compiler calls, not a blob injected into every context | not started |
| 13 | **Test Healer** (selector/timing/locator fixes only, never weakens an assertion — every heal produces a diff) **+ Regression Engine, including regression-test generation**: a `BUG_VERIFIED` Finding gets a permanent, executable regression test file written to the project's own test suite (not just a `Test` row) — application source is never touched; re-run only the requirements/tests the World Model says a diff actually affects | not started |
| 14 | **Environment Engineering**: Docker-based isolated environments, seed data/users, fault injection (latency, timeout, service failure, duplicate event, stale state). Unlocks Advanced: concurrency, failure/recovery, chaos | not started |
| 15 | **Security + Concurrency** hypothesis engine: cross-account access, privilege escalation, object enumeration, race conditions/duplicate actions — needs Phase 14's multi-identity/fault-injection environment to be real rather than single-case | not started |
| 16 | **Evaluation Lab + Harness Auditor**: multiple benchmark apps with known, seeded bugs; tracks the metrics in §42 (verified findings/compute, information gain/experiment, false-positive rate); harness/strategy changes must clear this bar before being kept — this is what makes Phase 8's "keep/revert" gate statistically meaningful instead of n=1 | not started |
| 17 | **Source connectors + durable multi-run architecture**: GitHub (App) as one `SourceProvider` implementation (never the core abstraction), immutable-commit resolution, isolated per-run workspace, Project-vs-Run state separation, crash-resume via existing checkpoint primitives (`LoopState`/`BudgetTracker`) hardened and actually tested against a mid-run kill | not started |
| 18 | **Software Knowledge Graph + Code Intelligence retrieval**: promote the flat `WorldModel` into a real linked graph (Requirement→Feature→Workflow→UI→API→Code→DB→Test→Finding) with `search_code`/`read_symbol`/`find_callers`-style tools and hybrid (lexical+semantic+graph) retrieval. Deferred this late deliberately — it's only worth its complexity against a real multi-file, multi-language codebase, not a 70-line example app | not started |
| 19 | **Visual / Accessibility / Desktop / Mobile execution channels** (Advanced testing areas) — new Executor channels behind the same Experiment/Observation/Oracle contracts Phase 6 already established, not a parallel system | not started |
| 20 | **Dashboard/UI + natural-language command bar + CI/GitHub PR integration** — the one genuinely separate product surface (a web frontend, its own stack decision). Deliberately last: it needs Phases 8–18's data model to actually have something worth displaying | not started |

**Code Fixer is removed from this roadmap, not merely deferred.** Per
explicit instruction: no autonomous code repair, no automatic PRs, no
automatic production fixes. The loop's output is a verified finding plus a
permanent regression test — application/user source is never modified by
this system. If that changes later it needs its own explicit ask, not a
revival of a shelved phase.

## 2026-09-01 scope reconciliation

A much larger spec was proposed (GitHub App-based source connectors, a
persistent Software Knowledge Graph, a formal multi-agent runtime, Memory/
Learning, Environment Engineering with fault injection, Security/Concurrency
testing, Healer/Fixer/Regression, an Evaluation Lab + Harness Auditor, and a
full web Dashboard with a natural-language command bar). Per explicit
instruction, this is **not** being built as one leap — the phase table above
is the incremental path there. Two things worth being explicit about:

**Agent-name mapping.** That spec names a fixed agent roster (Supervisor,
Cartographer, Explorer, Strategist, Executor, Oracle, Triager, Investigator,
Reproducer, Healer, Fixer, Learner, Harness Auditor). Every one of those
already exists here as a plain deterministic module, not an opaque
LLM-driven "Agent" class — `cartography/`, `explorer/browser.py`,
`strategist/scientist.py`, `execution/`, `oracle/oracle.py`,
`investigation/{triager,investigator,reproducer}.py`. That's intentional:
the same spec's own engineering rules say to prefer deterministic systems
over unnecessary LLM calls and that "the agent is not the product." The one
un-modularized role is **Supervisor** — today `orchestrator/job_runner.py`
plays that part directly as a linear state machine. It stays that way until
a phase actually needs non-linear control flow (retries across independent
agents, parallel experiments) that a flat script can't express — introducing
a `Supervisor` abstraction before that need exists would be exactly the kind
of unneeded abstraction the engineering rules warn against.

**Testing-area priority.** The requested Core-vs-Advanced testing split maps
onto the ordering above: functional/E2E/exploratory/regression (✅ done),
API/integration/system/business-logic/state-machine/data-integrity/temporal/
failure-recovery/authn/authz round out through Phase 13, and only then do the
Advanced areas (concurrency, security, performance, visual, accessibility,
desktop, mobile, chaos, code-level) get built — because most of them
(concurrency, chaos, real security testing) are honestly not meaningful
without Phase 14's environment engineering existing first to create the
conditions they need (multiple identities, controllable faults, isolated
state). Building them earlier would mean faking the conditions instead of
creating them.

**Explicitly large, separate workstreams** (not swallowed into a phase
number above because they're substantial enough to need their own planning
pass when their turn comes): the Software Knowledge Graph as a real graph
database (Phase 19), GitHub App production auth/webhooks (part of Phase 18),
and the web Dashboard (Phase 21) — a different frontend stack, not a CLI
extension.

## Why Phase 0+1 first (and only)

Per the spec's own §35/§37: build the runtime before any "intelligence." A
fake agent that returns placeholder strings is worse than no agent — it hides
the fact that nothing real is happening yet. Phase 1 ends with a real,
inspectable, persisted job lifecycle:

```
JOB_CREATED → REQUIREMENTS_RECEIVED → JOB_INITIALIZED
  → ANALYSIS_PENDING → WORLD_MODEL_PENDING → TESTING_PENDING → COMPLETED
```

Every transition is a persisted `Event`. `ANALYSIS_PENDING` runs a real (if
minimal) filesystem cartographer — no network calls, no guessing — and
optionally asks the local Ollama model for a one-paragraph summary of what it
found, which is the first genuine (non-stubbed) use of the model. Full
autonomous testing (explore/hypothesize/experiment) starts at Phase 4+.

## Phase 2 implementation notes

`src/veriforge/harness/` now sits between every agent-facing capability and
the outside world:

- `tools.py` — `ToolRegistry` + `ToolSpec` (name, description, risk, timeout,
  retry policy). Nothing is callable unless it's registered here.
- `permissions.py` — `PermissionPolicy` resolves a tool's `RiskLevel` to
  ALLOW / DENY / REQUIRES_CONFIRMATION via `DEFAULT_RISK_POLICY`
  (`domain/enums.py`). `BLOCKED` is never overridable. `REQUIRES_CONFIRMATION`
  fails closed (DENY) unless an explicit confirm callback approves it — no
  silent default-allow.
- `budget.py` — `BudgetTracker` wraps the persisted `LoopState` model; tracks
  tool-call count, token count (real counts once a provider reports them),
  and wall-clock runtime against configured limits.
- `executor.py` — `ToolExecutor.call(name, **kwargs)` is the only path that
  actually invokes a handler: checks permission → checks budget → runs with
  a real timeout (via a thread pool, not cooperative) → retries per the
  tool's `RetryPolicy` → publishes `TOOL_CALL_STARTED/SUCCEEDED/FAILED/DENIED`
  events for every attempt.
- `builtin_tools.py` — registers the three real capabilities Phase 1 needs
  (`filesystem.scan_repository` READ, `api.get` READ, `llm.generate`
  LOW_RISK) so the job runner goes through the harness instead of calling
  httpx/the cartographer/the LLM directly.

`src/veriforge/context/compiler.py` — `ContextCompiler.compile(world_model,
goal, ...)` ranks requirements (critical-first, then goal-keyword overlap)
and unknowns, trims to a max count, and attaches only tool name+description
(never full schemas) plus current budget constraints. `ContextBundle.
render_prompt()` turns that into the compact prompt text an LLM would
actually receive — verified against a real job run (see README) to produce
~25 lines instead of dumping the whole world model.

Not yet built (deferred to when an actual agent needs it): semantic/
embedding-based relevance ranking (Phase 8, using the locally pulled
`nomic-embed-text` model), context reset/compaction across long-running
sessions, and a human-in-the-loop `confirm` callback wired to the CLI for
HIGH_RISK tools (currently HIGH_RISK always denies since nothing risky
enough exists yet to need it).

## Phase 3 implementation notes

- `cartography/python_ast.py` — real `ast`-based static analysis (no LLM, no
  code execution). Detects Flask/FastAPI-style decorators (`@app.get(...)`,
  `@app.route(..., methods=[...])`), Django-style `path()`/`re_path()` calls,
  and stdlib `http.server`-style `do_<METHOD>` handlers (matching
  `self.path == "..."` / `self.path.startswith("...")`). Also collects
  imports and maps known ones (`sqlalchemy`, `psycopg2`, `pymongo`, ...) to
  persistence backends. `mentions_role_check` is a raw fact (an auth-looking
  identifier appears in that handler's AST — comments don't count, since
  they aren't part of the AST) — not a verdict.
- `cartography/cartographer.py` — combines the Phase 1 filesystem scan with
  the AST analysis into one repo-facts payload, registered as the harness
  tool `code.analyze_repository` (replaces the old `filesystem.scan_
  repository`-only analysis step).
- `requirements/invariants.py` — regex-based structuring of a classified
  Requirement into a machine-checkable dict: authorization (actor/action/
  object/expected), temporal (max_duration_seconds), data invariants
  (expected/forbidden HTTP status), ordering (before/after). Populates
  `Requirement.structured`; returns `None` rather than guessing when nothing
  matches.
- `world_model/builder.py` — the new `build_world_model()` cross-references
  each critical AUTHORIZATION/NEGATIVE requirement against discovered
  endpoints (action→HTTP method, object→path keyword) and folds the match
  (and whether that endpoint's handler mentions a role check) into the
  Unknown's rationale.

**Verified against the example app**: the cartographer found all 4 real
endpoints (`GET /`, `GET /projects`, `POST /projects`, `DELETE /projects/`),
correctly matched "Members cannot delete projects." to `DELETE /projects/`,
and flagged that its handler has no role/permission-check identifier — which
is exactly the intentional bug planted in `examples/example-app/app.py`. No
LLM was involved in producing that finding; it's pure static analysis plus
deterministic matching. Confirming it's an actual, exploitable bug (not just
"unverified") still requires the Executor/Oracle (Phase 6) to actually call
the endpoint as a member and observe the response.

Also fixed two real classifier gaps found while building this: "owner" is
now an authorization-hint keyword, and a bare HTTP status code (e.g. "404")
in a requirement now classifies it as a data invariant even without an
explicit hint word like "unique"/"duplicate".

## Phase 4 implementation notes

- `explorer/browser.py` — real Playwright automation, driven off the ARIA
  accessibility tree (`locator.aria_snapshot()`) rather than raw CSS
  selectors: this is the "precision mode: DOM/ARIA" path from spec §13/§14,
  reserving computer-use/vision for canvases, drag-drop, and other UIs the
  accessibility tree can't describe. `BrowserExplorer.explore(url)`:
  navigates, captures console messages and every network response, then
  bounded-auto-clicks up to `max_clicks` distinct elements whose accessible
  name doesn't look destructive (`delete`/`remove`/`archive`/...).
  Destructive-looking elements are recorded in `skipped_destructive`, never
  clicked — deciding to deliberately exercise a delete flow with intent is
  the Test Scientist's job (Phase 5) via the Executor/Oracle (Phase 6), not
  something a bounded explorer should stumble into.
- Re-observes the accessibility tree after every click, not just once at
  the start, so an element that only appears after an action (e.g. a
  "Delete" button that shows up once something has been created) actually
  gets discovered. Found and fixed a real race in the process: Playwright's
  `networkidle` can resolve a beat before a fetch's `.then()` continuation
  has finished mutating the DOM. Fixed with a poll-until-changed loop
  (`_observe_elements_after_change`, 100ms steps, 1.5s ceiling) instead of a
  fixed sleep — confirmed the flakiness this replaced by reproducing it
  directly (a fixed 300ms settle wait failed intermittently under pytest;
  the poll loop passed 5/5 reruns).
- Registered as the harness tool `browser.explore` (LOW_RISK, 60s timeout).
  `world_model/builder.py` now takes an optional `ExplorationResult`: each
  visited page becomes a `WorldModelState`, the click sequence becomes a
  `Workflow`, and each skipped-destructive element becomes an `Unknown`
  ("what happens when a user activates X?") for a future phase to actually
  test with intent.
- `examples/example-app/app.py` gained a `GET /ui` HTML frontend (fetch()
  calls against the existing JSON API) — the JSON-only API had nothing for
  a browser to click through. Its "Delete" button reaches the same
  intentionally-unchecked `DELETE /projects/<id>` endpoint Phase 3 already
  flagged via static analysis, so the bug is now reachable and observable
  through two independent paths (AST analysis and browser exploration).

**Verified against the example app** (both automated tests and a real CLI
run against a live server): exploration clicked "Create Project", the DOM
update revealed a "Delete" button, and it was correctly left unclicked and
recorded as a candidate Unknown — with real screenshots (`page_0.png`,
`page_1.png`) and real captured network events (`GET /projects`,
`POST /projects` → 201, `GET /projects` again) as evidence.

## Phase 5 implementation notes

- `strategist/scientist.py` — `rank_experiments(world_model)` turns every
  open (unresolved) `Unknown` into a scored `Experiment` using the formula
  from spec §12 (coverage + novelty + risk + historical_bug_likelihood +
  information_gain + change_relevance − cost − redundancy). Each axis is
  backed by a real, already-computed signal rather than an invented number:
  - `coverage` — is the requirement critical?
  - `novelty` — did this Unknown come from live browser exploration
    (Phase 4) or only static analysis?
  - `risk` — requirement kind (AUTHORIZATION/SECURITY weighted highest).
  - `historical_bug_likelihood` — the real Phase 3 signal: does the
    Unknown's rationale say the matched endpoint has *no*
    role/permission-check identifier?
  - `information_gain` — does the requirement have a structured invariant
    (Phase 3) an Oracle could mechanically check?
  - `change_relevance` — **honestly a constant placeholder** (0.5) —
    computing this needs git diff/blame integration, which no phase has
    built yet. Documented as uncomputed rather than faked.
  - `cost` / `redundancy` — requirement kind and duplicate-endpoint
    detection (a second Unknown matching the same `(method, path)` as one
    already ranked is penalized).
  Weights live in `DEFAULT_WEIGHTS`, a plain dict — the hook for a future
  Learner (Phase 17/25) to persist a tuned `Strategy` and pass its weights
  in, not built yet.
- `promote_to_tests(experiments, top_k=3)` marks the top-K ranked
  experiments `PLANNED` and the rest `HYPOTHESIS` (spec §24's Test
  lifecycle) — recorded, not discarded, since a future run's budget might
  cover more.
- `Unknown` gained a `requirement_id` field so an Experiment can trace back
  to the requirement that generated it (added when building this phase —
  it didn't exist before because nothing needed the link yet).
- Added `Experiment`/`Test` repositories to `Store`. `job_runner._step_
  testing` now persists real ranked experiments and tests instead of the
  old "0 experiments run" placeholder — still honestly 0 *executed* (no
  Executor/Oracle exists until Phase 6), but N real candidates are now
  generated, scored, and queued.

**Verified against the example app**: the Test Scientist correctly ranked
"Verify: Members cannot delete projects." (score 4.65) above all 5 other
candidates — including a same-topic Unknown discovered independently via
browser exploration (score 2.3, lower because it lacks the requirement
link's coverage/risk boost) — precisely because it carries the real
Phase 3 "no role check" signal, not because the answer was hardcoded.

## Phase 6 implementation notes

The Executor+Oracle scope is deliberately narrow: **one invariant kind**
(authorization/negative requirements with `structured.expected == "denied"`
that resolve to a concrete endpoint), executed **one experiment per job
run** (the highest-ranked executable candidate — everything else stays
queued). That's a real vertical slice, not a stub, and it's the one that
matters most for the example app's planted bug.

- `execution/http_executor.py` — `execute_authorization_check()` performs
  the actual sequence: POST to create a throwaway resource (found via the
  same object-keyword matching Phase 3/5 use — `find_creation_endpoint`) →
  GET to confirm it exists → the action under test (e.g. DELETE) sent with
  an `X-Role: <singular actor>` header → GET again to check whether the
  resource is actually gone. Every step becomes a persisted `Observation`.
  Auth simulation via an `X-Role` header is a documented MVP assumption —
  real multi-identity/session/JWT simulation is future work (spec §40's
  `multiple_test_identities`).
- `oracle/oracle.py` — `judge_authorization()` implements Oracle Level 1
  (exact assertion on HTTP status: 401/403 = denied, 2xx = allowed) *and*
  Level 3 (state comparison: is the resource still there afterward?). When
  both are available, the **state check is the ground truth** — a status
  code alone can lie (a handler that returns 200 but silently no-ops) — and
  disagreement between the two lowers confidence (0.7) rather than being
  silently ignored (agreement: 0.9). No state check at all falls back to
  status-only (0.6). Neither a clear denial nor a clear success status →
  `UNCERTAIN`, not a guess.
- `execution/experiment_runner.py` ties them together: `is_executable()`
  gates which requirements Phase 6 will even attempt (only
  `expected=="denied"` — the positive `"allowed_only_for_this_actor"` case
  and all non-authorization invariant kinds stay `HYPOTHESIS`/`PLANNED`,
  honestly unexecuted). On `FAIL`, produces a `Finding`
  (`SECURITY_FINDING` for authorization/negative/security kinds,
  `APPLICATION_BUG` otherwise) with an `Evidence` record per `Observation`.
- Added `TestRun`, `Observation`, `Finding`, `Evidence` repositories to
  `Store`. `job_runner._execute_top_experiment` walks the ranked
  experiments, executes the first executable one, updates the matching
  `Test`'s status (`EXECUTING` → `VERIFIED`/`FAILED`), and writes
  `observations.json` / `verdict.json` / `finding.json` — matching the
  artifact names from spec §11/§29 exactly.
- New MEDIUM_RISK tools `api.post`/`api.put`/`api.delete`, justified in
  `builtin_tools.py`: they're scoped to (a) the URL the user explicitly
  gave as the job's target, and (b) a resource the Executor itself just
  created for the experiment — never arbitrary pre-existing data, unlike a
  raw `database.DELETE` (which the spec correctly calls DESTRUCTIVE).

**A real bug found and fixed while building this**: `job.base_url` doubles
as both the browser explorer's entry point (which the README has users
point at `/ui`) and the API base the Executor calls against — but those
aren't the same path. A live CLI run against `--url http://localhost:8000/ui`
produced `UNCERTAIN` (404s) because the Executor was calling
`.../ui/projects` instead of `.../projects`. Fixed with `origin_of()`
(reduces any URL to its `scheme://host:port`) applied inside
`execute_authorization_check` itself, not just at the call site — plus a
regression test (`test_execute_authorization_check_uses_origin_not_the_
full_url_with_path`) so it can't silently reappear.

**Verified against the example app, end to end**: created a project via
POST, confirmed it existed via GET, deleted it as `role='member'` via
DELETE, confirmed it was actually gone via a second GET — and the Oracle
correctly concluded `FAIL`: the deletion was allowed when the requirement
says it should be denied. A real, evidence-backed `SECURITY_FINDING`, not a
hardcoded result — confirmed via both a direct Python reproduction and the
full CLI (`Verdict: FAIL`, `Findings: 1`).

## Phase 7 implementation notes

Runs only when Phase 6 already produced a FAIL + Finding — a PASS needs no
investigation.

- `investigation/triager.py` — `triage(verdict, requirement)` classifies
  into a `FailureCategory` from the verdict's own confidence (low
  confidence → `REQUIREMENT_AMBIGUITY`, not a confident blame) and the
  requirement's kind (AUTHORIZATION/NEGATIVE/SECURITY → `SECURITY_FINDING`,
  else `APPLICATION_BUG`). `UNCERTAIN` verdicts are always
  `REQUIREMENT_AMBIGUITY`.
- `investigation/reproducer.py` — `reproduce()` re-runs the exact same
  `run_experiment()` sequence once more. Agreement → the Test graduates to
  `BUG_VERIFIED`; disagreement overrides the category to `FLAKINESS` and
  the Test stays `TRIAGED`, not falsely confirmed.
- `investigation/investigator.py` — `build_root_cause()` ties Phase 3's
  static signal (does the handler even reference a role check?) + the
  Oracle's dynamic verdict + the reproduction result into one narrative,
  rather than repeating the Oracle's reasoning alone.
- `Finding` gained `root_cause` and `reproduced` fields. `run_experiment()`
  no longer guesses a category itself (that duplicated the Triager) — it
  sets `UNKNOWN` and `job_runner._investigate_finding` always refines it
  when a Finding exists. New artifact: `investigation.json`.

**Verified live**: against the example app, `finding.category` correctly
resolves to `SECURITY_FINDING` (0.9 confidence), `reproduced=true` (the
bug is deterministic — reproduced on an independent second run), and
`root_cause` reads: *"...Static analysis of app.py:97 found no
role/permission-check identifier... Reproduced on a second independent
run -- consistent result, not flaky."* — static + dynamic + reproduction
evidence genuinely tied together, not templated filler.

## Phase 8 implementation notes

No new infrastructure — same SQLite-backed `Store`/`TypedRepository` from
Phase 1, plus two repos that were missing (`store.projects`, `store.
strategies`) and query patterns over what already existed. See the earlier
"what backs Phase 8 memory" answer for the full rationale; summarized:

- **A real bug fixed first, without which none of this could work**:
  `Requirement.id` was a random UUID generated fresh on every parse, so the
  "same" requirement text got a *different* id every run — semantic memory
  could never match a later run's Unknown to an earlier run's Finding.
  Fixed with `domain/models.stable_id(prefix, *parts)` (a truncated SHA-256
  of the parts, not `uuid4`), used for `Requirement.id = stable_id("req",
  project_id, source_text)`. Caught by writing the cross-run integration
  test first and watching it fail on a `0 == 1` assertion.
- **CLI project reuse**: `cli/main.py` now looks up an existing `Project` by
  `repo_path` before creating a new one, and actually persists it (`Project`
  existed since Phase 1 but was never saved to the store before this).
- `memory/episodic.py` — `get_run_history`/`get_past_findings`: plain
  `list_by_project` queries, nothing new.
- `memory/semantic.py` — `apply_semantic_memory(store, world_model)` maps
  `requirement_id -> most recent prior Finding` and marks a matching
  Unknown `resolved=True` with a rationale note, mutating the world model
  in place. Exact-key lookup, deliberately not embedding similarity.
- `memory/procedural.py` — `get_active_strategy` loads a project's
  highest-version `Strategy`, creating a default v1 (`DEFAULT_WEIGHTS`) the
  first time. `job_runner._step_testing` now passes `strategy.weights` into
  `rank_experiments()` instead of the bare default — a real hook, even
  though nothing yet proposes a v2.
- `learning/engine.py` — `record_run_learning` appends one `Learning` row
  per run with this run's metric (verified-findings-per-experiment-
  executed) and compares it to the average of all prior runs' recorded
  metrics for this project. Below `_MIN_RUNS_FOR_DECISION` (5) prior runs,
  `kept=None` — "insufficient data" is the honest answer, not a guessed
  verdict. A real, statistically meaningful comparison across varied runs
  is the Evaluation Lab's job (Phase 17); this is the mechanism it plugs
  into.

**A known, deliberate limitation**: once memory resolves an Unknown, the
current run's Test Scientist skips it entirely (already-resolved Unknowns
are excluded from ranking) — so if a bug were later *fixed*, nothing here
would notice, since the requirement just stops being tested. Re-verifying
previously-found bugs to confirm a fix is the Regression Engine's job
(Phase 13), not Memory's — conflating them here would mean re-testing
*everything* every run "just in case," defeating the point of remembering.

**Verified live**, two real CLI runs against the same `--repo`: both
resolved to the same `project` id. Run 1: `Strategy version: 1`,
`Verdict: FAIL`, `learning.json` shows `kept: null` ("Only 0 prior runs").
Run 2: `Resolved from memory: 1`, `Hypotheses generated` dropped from 6 to
5 (the confirmed bug excluded from ranking), the top-ranked hypothesis
correctly shifted to the next candidate (the 404-vs-500 data invariant),
and `learning.json` shows `baseline_metric: 1.0` — exactly run 1's
measured metric — with `kept: null` again (still only 1 prior run, below
the threshold of 5).

## Phase 9 implementation notes

Two of the four planned invariant kinds became genuinely executable;
temporal and ordering deliberately did not — see below for why.

- **A real gap fixed first**: `requirements/invariants.py`'s data-invariant
  extractor only ever produced `expected_status`/`forbidden_status` — no
  `action`/`object`, so `match_endpoint_for_requirement` could never
  resolve it to a concrete endpoint and it was permanently unexecutable.
  Added `_infer_action_object_generic()`: a verb-first heuristic (first
  recognized action word, then the next non-stopword word as the object) —
  deliberately scoped to that one phrasing shape ("Deleting a project
  that... must...") rather than general prose, since guessing wrong is
  worse than leaving it unset.
- **`execute_data_invariant_check`** (`http_executor.py`) — calls the
  matched endpoint against a guaranteed-nonexistent resource id, no
  creation step needed. **`judge_data_invariant`** (Oracle Level 1 only):
  status == expected → PASS, status == forbidden → FAIL, neither →
  UNCERTAIN.
- **`execute_allowed_only_for_actor_check`** — the positive counterpart to
  Phase 6's authorization check: two independent throwaway resources, one
  action attempted as the named actor (e.g. "owner"), one as a synthesized
  `not-<actor>` role. **`judge_allowed_only_for_actor`**: actor must
  succeed *and* the other role must be denied, or it isn't actually
  exclusive — reusing two separate resources so one attempt can't
  contaminate the other's presence check.
- `experiment_runner.py` restructured from a single authorization-only
  function into a dispatcher (`is_executable`/`run_experiment` branch on
  `requirement.structured["expected"]` / the presence of
  `expected_status`) — a fourth kind slots in the same way later.
- **A second real classifier gap fixed**: "Only an owner may delete a
  project." was never flagged critical (no "must"/"cannot"/etc.), so it
  never even became an Unknown despite being a real access-control
  requirement. Added `"only"` to the criticality keyword list.
- **Temporal and ordering stay unexecuted, on purpose.** Inferring
  action/object for temporal phrasing ("Project creation must return
  within 2 seconds" — object-then-action-noun order) needs real sentence
  structure handling that the verb-first heuristic above would get wrong
  as often as right; guessing there would violate this project's own
  "don't guess" rule. Ordering invariants need a multi-step pipeline to
  validate against, which the example app doesn't have. Both wait for a
  requirement-parsing approach that can actually earn confidence, not
  heuristics stretched past what they're honestly good for.

**Verified live**: re-ran the exact two-run Phase 8 demo. Run 1 unchanged
(confirms "Members cannot delete projects."). Run 2 — previously reporting
`Tests executed: 0` because nothing else was executable — now runs the
next-ranked candidate, "Only an owner may delete a project.", and confirms
a **second real, independent bug**: the app has no role differentiation at
all, so a synthesized "not-owner" role can delete a project exactly as
easily as "owner" can (`Verdict: FAIL`, `reproduced: true`,
`SECURITY_FINDING`, confidence 0.85) — found via the new capability, not
hardcoded.

## Local-first model policy

- Default LLM provider is `OllamaProvider`, talking to `http://localhost:11434`.
- Default model: `llama3.2:3b` (fast, already pulled). Configurable via
  `VERIFORGE_LLM_MODEL` or `--model`.
- `LLMProvider` is an abstract interface (`src/veriforge/llm/provider.py`) —
  a hosted-API provider can be added later without touching orchestration code.
- Embeddings (for future semantic memory, phase 8) will use `nomic-embed-text`,
  already pulled locally.
