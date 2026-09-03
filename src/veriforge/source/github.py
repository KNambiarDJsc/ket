"""GitHubSourceProvider (Phase 17): clones a public GitHub repository URL
into an isolated per-job workspace via a real `git clone`, then reads back
the exact commit it landed on -- never assumed, the same "real signal,
never guessed" discipline as every other git-backed feature in this
project (regression/change_impact.py, environment/docker_env.py).

Scope, honestly: public HTTPS clone only. GitHub App authentication
(private repos, installation tokens, webhooks) is real, separate
infrastructure the spec calls out as its own workstream (see docs/
PHASES.md's Phase 17/18 notes) -- building it now, with no App registration
to test it against, would mean guessing at an auth flow rather than
verifying one. A private repo fails with a clear git error (authentication
required), not a silently wrong answer.

Isolated per-run workspace: every `resolve()` clones into its own
`workdir/sources/<random-id>` directory, never reused across jobs -- two
runs against the same URL never see each other's clone, and a job that
fails mid-clone can't leave a half-cloned directory for the next run to
trip over.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

from veriforge.source.provider import ResolvedSource

_CLONE_TIMEOUT_SECONDS = 120.0
_COMMIT_TIMEOUT_SECONDS = 10.0

_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?/?$"
    r"|^git@github\.com:[\w.-]+/[\w.-]+?(\.git)?$"
)


class GitHubCloneError(RuntimeError):
    pass


def is_github_url(spec: str) -> bool:
    return bool(_GITHUB_URL_RE.match(spec.strip()))


def display_name(spec: str) -> str:
    """"https://github.com/owner/repo(.git)" -> "owner/repo" -- for a
    friendlier Project name than a random clone-directory name."""
    match = re.search(r"github\.com[:/](?P<slug>[\w.-]+/[\w.-]+?)(\.git)?/?$", spec.strip())
    return match.group("slug") if match else spec


class GitHubSourceProvider:
    def resolve(self, spec: str, workdir: Path) -> ResolvedSource:
        dest = workdir / "sources" / uuid.uuid4().hex[:12]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", spec, str(dest)],
                capture_output=True, text=True, timeout=_CLONE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubCloneError(f"failed to clone {spec!r}: {exc}") from exc
        if result.returncode != 0:
            raise GitHubCloneError(f"git clone {spec!r} exited {result.returncode}: {result.stderr.strip()}")

        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(dest), capture_output=True, text=True, timeout=_COMMIT_TIMEOUT_SECONDS,
        )
        commit_sha = commit_result.stdout.strip() if commit_result.returncode == 0 else None
        return ResolvedSource(local_path=str(dest), commit_sha=commit_sha)
