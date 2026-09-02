"""Real Docker tests (Phase 14): skip gracefully if the Docker daemon isn't
reachable, same pattern as test_ollama_provider.py's live-backend test --
everything else in this suite is hermetic, but this genuinely needs the
real thing to mean anything.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from veriforge.environment.docker_env import (
    ManagedDockerEnvironment,
    _docker_executable,
    docker_available,
)

EXAMPLE_DB_APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "example-db-app"

pytestmark = pytest.mark.skipif(not docker_available(), reason="Docker daemon is not reachable")


def _container_is_running(name: str) -> bool:
    # Same PATH fallback as docker_env.py's own calls -- a bare "docker" can
    # fail to resolve from a Python subprocess on this machine even though
    # it's on an interactive shell's PATH (see docker_env.py's docstring).
    result = subprocess.run(
        [_docker_executable(), "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=15,
    )
    return name in result.stdout


def test_managed_docker_environment_runs_a_real_isolated_container():
    with ManagedDockerEnvironment(str(EXAMPLE_DB_APP_DIR), container_port=8001) as env:
        assert _container_is_running(env.name)

        resp = httpx.get(env.base_url + "/")
        assert resp.status_code == 200
        assert resp.json()["service"] == "veriforge-example-db-app"

        # A fresh container gets a fresh filesystem -- no leftover data.db
        # from any previous run, exactly the isolation guarantee this phase
        # exists to provide.
        listing = httpx.get(env.base_url + "/projects").json()
        assert listing["projects"] == []

        created = httpx.post(env.base_url + "/projects").json()
        assert "id" in created

    # Teardown is guaranteed on __exit__, not best-effort cleanup a caller
    # might forget.
    assert not _container_is_running(env.name)


def test_two_environments_get_independent_state():
    with ManagedDockerEnvironment(str(EXAMPLE_DB_APP_DIR), container_port=8001) as env_a:
        httpx.post(env_a.base_url + "/projects")
        with ManagedDockerEnvironment(str(EXAMPLE_DB_APP_DIR), container_port=8001) as env_b:
            listing_b = httpx.get(env_b.base_url + "/projects").json()
            assert listing_b["projects"] == []  # env_b never sees env_a's data

        listing_a = httpx.get(env_a.base_url + "/projects").json()
        assert len(listing_a["projects"]) == 1  # env_a is unaffected by env_b existing


def test_teardown_happens_even_when_the_with_block_raises():
    name = None
    with pytest.raises(RuntimeError):
        with ManagedDockerEnvironment(str(EXAMPLE_DB_APP_DIR), container_port=8001) as env:
            name = env.name
            raise RuntimeError("boom")
    assert name is not None
    assert not _container_is_running(name)
