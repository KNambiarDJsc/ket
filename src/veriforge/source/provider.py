"""Source Providers (Phase 17: "GitHub (App) as one SourceProvider
implementation, never the core abstraction"): resolves a job's `--repo`
input into a real, local, analyzable directory. A local filesystem path is
the trivial case every prior phase already relied on; Phase 17 adds a real
remote source (a GitHub URL) that needs cloning into an isolated workspace
first.

`SourceProvider` is the abstraction; nothing above `resolve_source_spec`
(cartographer, JobRunner, the CLI) should ever special-case "is this a
GitHub URL" -- that question is answered once, and every other module
keeps working against a plain local path, exactly as before this phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ResolvedSource:
    local_path: str
    commit_sha: str | None  # None when not a git repo, or the commit couldn't be read back


class SourceProvider(Protocol):
    def resolve(self, spec: str, workdir: Path) -> ResolvedSource: ...
