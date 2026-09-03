"""LocalPathSourceProvider: the trivial case every prior phase already
relied on -- `spec` is already a path on disk. Resolves its current commit
via the same real `git rev-parse` this project already uses for change-
impact tracking (regression/change_impact.py) rather than duplicating that
logic; `None` when it isn't a git repo at all, the same honest-degradation
shape `current_commit` already guarantees.
"""
from __future__ import annotations

from pathlib import Path

from veriforge.regression.change_impact import current_commit
from veriforge.source.provider import ResolvedSource


class LocalPathSourceProvider:
    def resolve(self, spec: str, workdir: Path) -> ResolvedSource:
        del workdir  # a local path needs no workspace of its own
        return ResolvedSource(local_path=spec, commit_sha=current_commit(spec))
