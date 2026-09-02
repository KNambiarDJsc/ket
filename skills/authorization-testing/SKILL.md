---
name: authorization-testing
description: How VeriForge's Executor and Oracle verify authorization requirements that say who is allowed or denied to do something, using actor/action/object structure and direct state comparison rather than trusting HTTP status alone.
version: 1
---

# Authorization Testing

Use this when a requirement says an actor is (or isn't) allowed to perform
an action — "Members cannot delete projects.", "Only an owner may delete a
project." These are the highest-`risk`-weighted requirement kinds in the
Test Scientist's scoring formula (`strategist/scientist.py`), and for good
reason: an authorization bug is silent by default. Nothing crashes; the
wrong person just succeeds.

## Structure first

`requirements/invariants.py` extracts `{actor, action, object, expected}`
from two phrasings:

- Negative: "X cannot/must not/may not Y Z." → `expected: "denied"`
- Positive: "Only X may Y Z." → `expected: "allowed_only_for_this_actor"`

Without this structure there is nothing to execute — a requirement that
doesn't match either pattern stays `structured=None` and is honestly never
tested, not guessed at.

## Never trust status alone

The single most important lesson baked into this system's Oracle
(`oracle/oracle.py:judge_authorization`): an HTTP status code can lie. A
handler can return `200` and silently no-op, or return `403` and still
mutate state. That's why `execute_authorization_check`
(`execution/http_executor.py`) always does a **state check** — create a
throwaway resource, act on it, then check via a follow-up read whether it
actually changed — and the Oracle treats state as ground truth when status
and state disagree (confidence drops to 0.7 instead of 0.9, but the state
reading wins, not the status).

For the positive case (`allowed_only_for_this_actor`), exclusivity requires
**two independent checks**: the named actor must succeed, *and* a
different role must be denied. Confirming only the first half is not
enough — see `execute_allowed_only_for_actor_check`, which deliberately
uses two separate throwaway resources so one attempt's outcome can't
contaminate the other's presence check.

## The MVP assumption, stated plainly

Actor identity is simulated via an `X-Role` header — a convention this
project's own example app happens to use, not a general auth mechanism.
Real session/cookie/JWT-based multi-identity simulation is still future
work. Don't extend this pattern to a real target without checking how that
target actually authenticates.

## When this doesn't apply

If a requirement doesn't resolve to a concrete `(method, path)` endpoint —
`world_model.builder.match_endpoint_for_requirement` returns `None` — it
stays an open `Unknown`, not a guessed pass or fail. See
`data-integrity-testing` when the question is instead "did the data
actually change," not "was the actor allowed to change it."
