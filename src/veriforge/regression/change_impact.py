"""Change-impact analysis (Phase 13): real `git diff` integration, closing
a gap two earlier phases explicitly deferred rather than guessed at:

- Phase 5's Test Scientist scored `change_relevance` as a constant
  placeholder (0.5) because "computing this needs git diff/blame
  integration, which no phase has built yet" (strategist/scientist.py).
- Phase 8's semantic memory explicitly punted re-verifying a previously
  confirmed bug to "the Regression Engine's job (Phase 13), not Memory's"
  (memory/semantic.py) -- this module is what makes that re-verification
  possible: knowing whether the code behind a prior Finding has actually
  changed since that Finding was recorded.

`None` (not an empty set) means "can't tell" -- not a git repo, git isn't
installed, or the reference commit is unreachable (e.g. after a rebase or
a shallow clone). Treating "can't tell" as "nothing changed" would be
silently wrong exactly when this feature matters most: a real change that
this module fails to see would mean a stale memory-resolved bug (or an
uncomputed ranking signal) never gets re-examined.
"""
from __future__ import annotations

import subprocess

_GIT_TIMEOUT_SECONDS = 10.0


def current_commit(repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def changed_files_since(repo_path: str, since_commit: str) -> set[str] | None:
    """Repo-relative paths that differ between `since_commit` and the
    current working tree (uncommitted changes included, via `git diff
    <since_commit>` with no second ref)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since_commit],
            cwd=repo_path, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}
