"""resolve_source_spec: the one place that decides whether `--repo` names a
local path or a remote GitHub URL, so every other module (cartographer,
JobRunner, the CLI) keeps working against a plain local directory, unaware
Phase 17 added a second possible origin.
"""
from __future__ import annotations

from pathlib import Path

from veriforge.source.github import GitHubSourceProvider, is_github_url
from veriforge.source.local import LocalPathSourceProvider
from veriforge.source.provider import ResolvedSource


def resolve_source_spec(spec: str, workdir: Path) -> ResolvedSource:
    provider = GitHubSourceProvider() if is_github_url(spec) else LocalPathSourceProvider()
    return provider.resolve(spec, workdir)
