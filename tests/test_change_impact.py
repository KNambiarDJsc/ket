import subprocess

from veriforge.regression.change_impact import changed_files_since, current_commit


import os

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _git(repo_path, *args):
    subprocess.run(["git", *args], cwd=repo_path, check=True, capture_output=True, text=True, env=_GIT_ENV)


def init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_current_commit_returns_a_hash_for_a_real_repo(tmp_path):
    repo = init_repo(tmp_path)
    commit = current_commit(str(repo))
    assert commit is not None
    assert len(commit) == 40  # a full SHA-1 hash


def test_current_commit_returns_none_for_a_non_git_directory(tmp_path):
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    assert current_commit(str(non_repo)) is None


def test_changed_files_since_detects_a_real_change(tmp_path):
    repo = init_repo(tmp_path)
    first_commit = current_commit(str(repo))

    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change a.py")

    changed = changed_files_since(str(repo), first_commit)
    assert changed == {"a.py"}


def test_changed_files_since_empty_set_when_nothing_changed(tmp_path):
    repo = init_repo(tmp_path)
    commit = current_commit(str(repo))

    changed = changed_files_since(str(repo), commit)
    assert changed == set()


def test_changed_files_since_returns_none_for_unreachable_commit(tmp_path):
    repo = init_repo(tmp_path)
    assert changed_files_since(str(repo), "0" * 40) is None


def test_changed_files_since_returns_none_for_non_git_directory(tmp_path):
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    assert changed_files_since(str(non_repo), "HEAD~1") is None
