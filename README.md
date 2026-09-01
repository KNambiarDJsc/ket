# VeriForge

Autonomous Software Verification & Testing OS. See `docs/PHASES.md` for the
full architecture-to-phase mapping and the prior art (Ralph loop, Anthropic
harness-engineering, EnvHarness, Claude Skills) this design draws from.

This repo currently implements **Phase 0-9** (adds Project persistence/reuse
across runs, episodic/semantic/procedural Memory, evaluation-gated
Learning, and two more executable invariant kinds — data-invariant status
checks and the positive "only X may do this" authorization case; running
the same `--repo` twice, the second run recognizes a bug the first run
already confirmed, then executes the *next* candidate and confirms a
second, independent bug; see `docs/PHASES.md` for details): a real,
persisted job
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
Everything past that (Triager/Investigator/Reproducer to classify and
root-cause other kinds of failures, self-healing, skills, evaluation
lab...) is future phase work — see `docs/PHASES.md` for the tracker.

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

## Tests

```bash
./.venv/Scripts/python -m pytest
```

One test (`test_live_ollama_smoke`) exercises the real local Ollama backend
and skips gracefully if Ollama isn't running — everything else is hermetic.

## Local-first model policy

Default LLM provider is `veriforge.llm.ollama_provider.OllamaProvider`,
talking to `http://localhost:11434`. Override with `--model` / the
`VERIFORGE_LLM_MODEL` env var, or point `VERIFORGE_OLLAMA_HOST` elsewhere.
`veriforge.llm.provider.LLMProvider` is the abstract interface every future
agent depends on — a hosted-API provider can be dropped in later without
touching orchestration, cartography, or CLI code.
