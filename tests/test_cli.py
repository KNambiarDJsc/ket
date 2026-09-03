"""CLI-level tests for `veriforge verify` (Phase 17 adds --repo-as-GitHub-URL
and --subdir; this is also the first test coverage of cli/main.py's own
Project-reuse/Job-construction wiring, which had none before).
"""
from __future__ import annotations

import subprocess

import pytest
from typer.testing import CliRunner

from veriforge.cli.main import app

runner = CliRunner()

_REAL_REPO_URL = "https://github.com/KNambiarDJsc/ket.git"


def _github_reachable() -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-remote", _REAL_REPO_URL, "HEAD"], capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def test_verify_against_a_local_repo_still_works_unchanged(tmp_path, example_app_server):
    result = runner.invoke(app, [
        "verify",
        "--repo", "examples/example-app",
        "--requirements", "examples/requirements.md",
        "--url", example_app_server + "/ui",
        "--workdir", str(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert "FAIL" in result.output
    assert "Cloned" not in result.output  # a local path is never cloned


@pytest.mark.skipif(not _github_reachable(), reason="github.com is not reachable")
def test_verify_clones_a_github_url_and_analyzes_the_given_subdir(tmp_path, example_app_server):
    result = runner.invoke(app, [
        "verify",
        "--repo", _REAL_REPO_URL,
        "--subdir", "examples/example-app",
        "--requirements", "examples/requirements.md",
        "--url", example_app_server + "/ui",
        "--workdir", str(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert "Cloned" in result.output
    assert "Members cannot delete projects" in result.output
    assert "FAIL" in result.output

    cloned_dirs = list((tmp_path / "sources").iterdir())
    assert len(cloned_dirs) == 1
    assert (cloned_dirs[0] / "examples" / "example-app" / "app.py").exists()


# ---- Phase 20: --post-pr and the dashboard command ----

def test_verify_with_post_pr_but_no_token_warns_and_does_not_crash(tmp_path, example_app_server, monkeypatch):
    monkeypatch.delenv("VERIFORGE_GITHUB_TOKEN", raising=False)
    result = runner.invoke(app, [
        "verify",
        "--repo", "examples/example-app",
        "--requirements", "examples/requirements.md",
        "--url", example_app_server + "/ui",
        "--workdir", str(tmp_path),
        "--post-pr", "KNambiarDJsc/ket#1",
    ])

    assert result.exit_code == 0, result.output
    assert "VERIFORGE_GITHUB_TOKEN is not set" in result.output


def test_dashboard_command_is_registered():
    result = runner.invoke(app, ["dashboard", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--workdir" in result.output
