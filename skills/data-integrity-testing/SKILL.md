---
name: data-integrity-testing
description: How VeriForge's DB Executor and Oracle verify data-integrity requirements by reading the database directly instead of trusting an application's own API — this matters because a soft-delete bug can look correct through the API alone.
version: 1
---

# Data-Integrity Testing

Use this when a requirement is about what actually happened to stored
data, not about who was allowed to trigger it — "Deleted X must be
permanently removed from the database, not merely hidden."

## The core problem this exists to solve

Every earlier Oracle level in this system (Phases 6/9/10) verifies state by
calling the application's own API again — a follow-up GET, a listing
endpoint. That's fine when the bug is "the wrong actor could act," but it
is structurally blind to a specific, common bug shape: **an application
that hides something from its own read path without actually removing
it.** A soft delete (`UPDATE ... SET deleted = 1` instead of `DELETE FROM
...`) passes every API-only state check by construction, because the
API's own GET filters `WHERE deleted = 0` — of course it "looks" gone.

The only way to catch this is to stop trusting the application's account
of its own data and read the table directly. That's the entire point of
`execution/db_executor.py`.

## The pattern

1. Create a throwaway resource via the API (`find_creation_endpoint` — same
   object-keyword match every other Executor function uses).
2. Perform the action under test via the API (e.g. DELETE).
3. **Bypass the API entirely** and run a direct, read-only `SELECT COUNT(*)
   FROM <table> WHERE id = ?` against the database file
   (`database.query_sqlite`, a harness tool that refuses anything but a
   `SELECT` — this observes, it never mutates).
4. `judge_db_removal`: any nonzero row count is a violation, full stop —
   there is no "it agreed with the API so confidence is lower" branch here,
   because the database read *is* the ground truth this whole check exists
   to establish. There's nothing more authoritative to disagree with.

## Table name safety

The table name comes from the same `object_keyword()` match used to
resolve the requirement to an endpoint — but a table name gets
interpolated directly into SQL (identifiers can't be parameterized the way
values can). Always validate it against `^[A-Za-z_][A-Za-z0-9_]*$` before
building the query string, and let an unsafe name fail loudly rather than
be interpolated blind. The resource id, by contrast, always goes through
`params`, never string formatting.

## Requires an explicit `--db-path`

Like `--url`, the database path is never inferred from source — guessing a
connection string wrong is worse than not checking at all, and could be
actively unsafe. Without it, a `db_check` requirement stays queued, not
attempted-and-failed.

## When this doesn't apply

If the question is "was the actor allowed to do this," not "did the data
actually change the way it claims," see `authorization-testing` instead —
piling a database read onto every check regardless of what's being asked
would just be noise.
