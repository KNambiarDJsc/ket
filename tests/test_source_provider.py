import subprocess

import pytest

from veriforge.source.github import GitHubCloneError, GitHubSourceProvider, display_name, is_github_url
from veriforge.source.local import LocalPathSourceProvider
from veriforge.source.resolve import resolve_source_spec

_REAL_REPO_URL = "https://github.com/KNambiarDJsc/ket.git"


def _github_reachable() -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "https://github.com/KNambiarDJsc/ket.git", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


# ---- is_github_url / display_name ----

@pytest.mark.parametrize("url", [
    "https://github.com/owner/repo",
    "https://github.com/owner/repo.git",
    "https://github.com/owner/repo/",
    "git@github.com:owner/repo.git",
])
def test_is_github_url_matches_real_url_shapes(url):
    assert is_github_url(url) is True


@pytest.mark.parametrize("spec", [
    "/local/path/to/repo",
    "examples/example-app",
    "C:\\Users\\me\\repo",
    "https://gitlab.com/owner/repo",
])
def test_is_github_url_rejects_non_github_specs(spec):
    assert is_github_url(spec) is False


def test_display_name_extracts_owner_slash_repo():
    assert display_name("https://github.com/KNambiarDJsc/ket.git") == "KNambiarDJsc/ket"
    assert display_name("https://github.com/KNambiarDJsc/ket") == "KNambiarDJsc/ket"


# ---- LocalPathSourceProvider ----

def test_local_path_source_provider_resolves_a_real_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, timeout=10)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True, timeout=10)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, capture_output=True, timeout=10)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True, timeout=10)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, timeout=10)

    resolved = LocalPathSourceProvider().resolve(str(repo), tmp_path)

    assert resolved.local_path == str(repo)
    assert resolved.commit_sha is not None
    assert len(resolved.commit_sha) == 40


def test_local_path_source_provider_handles_a_non_git_directory(tmp_path):
    plain_dir = tmp_path / "not_a_repo"
    plain_dir.mkdir()

    resolved = LocalPathSourceProvider().resolve(str(plain_dir), tmp_path)

    assert resolved.local_path == str(plain_dir)
    assert resolved.commit_sha is None


# ---- GitHubSourceProvider, against the real public repo ----

@pytest.mark.skipif(not _github_reachable(), reason="github.com is not reachable")
def test_github_source_provider_clones_a_real_public_repo(tmp_path):
    resolved = GitHubSourceProvider().resolve(_REAL_REPO_URL, tmp_path)

    from pathlib import Path
    assert Path(resolved.local_path).is_dir()
    assert (Path(resolved.local_path) / "examples" / "example-app" / "app.py").exists()
    assert resolved.commit_sha is not None
    assert len(resolved.commit_sha) == 40


@pytest.mark.skipif(not _github_reachable(), reason="github.com is not reachable")
def test_github_source_provider_two_resolves_get_independent_directories(tmp_path):
    first = GitHubSourceProvider().resolve(_REAL_REPO_URL, tmp_path)
    second = GitHubSourceProvider().resolve(_REAL_REPO_URL, tmp_path)

    assert first.local_path != second.local_path


def test_github_source_provider_raises_clearly_on_a_bad_url(tmp_path):
    with pytest.raises(GitHubCloneError):
        GitHubSourceProvider().resolve("https://github.com/this-owner-does-not-exist-xyz/nope.git", tmp_path)


# ---- resolve_source_spec dispatch ----

def test_resolve_source_spec_dispatches_local_for_a_plain_path(tmp_path):
    plain_dir = tmp_path / "repo"
    plain_dir.mkdir()

    resolved = resolve_source_spec(str(plain_dir), tmp_path)

    assert resolved.local_path == str(plain_dir)


@pytest.mark.skipif(not _github_reachable(), reason="github.com is not reachable")
def test_resolve_source_spec_dispatches_github_for_a_github_url(tmp_path):
    resolved = resolve_source_spec(_REAL_REPO_URL, tmp_path)

    from pathlib import Path
    assert Path(resolved.local_path).exists()
    assert resolved.local_path != _REAL_REPO_URL
