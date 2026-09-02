---
name: api-contract-testing
description: How VeriForge verifies API and integration-contract requirements that name their own endpoint directly in the text: single-endpoint reachability and multi-endpoint create-then-list schema consistency checks.
version: 1
---

# API / Integration Contract Testing

Use this when a requirement names its own endpoint(s) literally in the
text — "The service must expose a health check at GET /.", "A newly
created project must appear in GET /projects immediately after creation."

## Why these don't need endpoint fuzzy-matching

Every authorization/data-invariant requirement (see `authorization-testing`,
`data-integrity-testing`) describes an action in prose ("Members cannot
delete projects") and has to be *resolved* to a concrete `(method, path)`
via action/object keyword matching against AST-discovered routes. Contract
requirements skip that step entirely — the method and path are literal in
the sentence. `world_model.builder.resolve_literal_endpoint` still checks
whether static analysis *independently* found that same route (real
evidence, cited by source_file:line) and falls back to a synthesized
endpoint from the requirement's own text when it didn't — a requirement
naming a route nobody implemented is itself a finding worth surfacing, not
a reason to skip the check.

## Two shapes, two Oracle judgments

- **`endpoint_exposed`** (single endpoint): call it exactly as declared,
  no setup needed. `judge_endpoint_exposure` — 2xx/3xx is a PASS, anything
  else is a FAIL. This is the cheapest possible check in the whole system;
  don't build anything fancier for it.

- **`creation_visible_in_listing`** (a genuine multi-endpoint contract):
  POST creates a resource, then GET the *separately named* listing
  endpoint and search its response (recursively — envelope shape varies,
  a bare list vs. `{"projects": [...]}`) for an entry matching the created
  id. `judge_creation_visibility` checks two independent things: does the
  resource show up at all (`not_found_in_listing` if not), and do its
  fields still match what the creation response returned
  (`schema_mismatch` if not) — a real request/response schema-consistency
  assertion, not just a presence check.

## An honest PASS is a feature, not a bug you missed

Unlike the authorization bugs found in Phases 6/9, both of the shapes
above genuinely PASS against VeriForge's own example apps most of the
time. That's deliberate evidence the Oracle isn't just tuned to manufacture
findings — it reports what it actually observes, in either direction.

## What's explicitly out of scope here

True service-to-service workflows (a contract spanning two *different*
services, not two endpoints of the same app) have no executor yet — there
is no multi-service fixture to validate one against, and faking one just
to exercise the code path would be exactly the kind of invented signal
this system's own engineering rules refuse to produce.
