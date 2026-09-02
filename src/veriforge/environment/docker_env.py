"""Docker-based isolated environments (Phase 14 Environment Engineering,
spec §9/§22): the environment itself becomes a controllable, mutable
subject VeriForge builds and tears down, not an assumption that "something
is already running at --url" (every prior phase's model). Shells out to
the `docker` CLI directly via subprocess -- same reasoning as
`regression/change_impact.py` shelling out to `git` rather than adding a
Python SDK dependency: the CLI is what's actually guaranteed present when
Docker is available at all, and this project doesn't otherwise depend on
the `docker` package.

Every failure mode here is honest, not silently swallowed: `docker_
available()` is a real, cheap check callers should use to decide whether
to attempt this at all (mirroring the local-first Ollama pattern -- "not
running" degrades gracefully, it doesn't get faked). Once a caller commits
to `ManagedDockerEnvironment`, a build/run failure raises
`DockerUnavailableError` rather than pretending an environment exists.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

# Observed empirically: a fresh subprocess's `docker info`/`docker rm -f`
# against Docker Desktop's VM-backed engine can take noticeably longer than
# the same command run from an already-warm interactive shell -- generous
# on purpose, since callers (docker_available() especially) should be
# treating "unreachable" as a real, honest signal, not an artifact of an
# impatient timeout.
_DOCKER_TIMEOUT_SECONDS = 15.0
_BUILD_TIMEOUT_SECONDS = 180.0
_RUN_TIMEOUT_SECONDS = 20.0
_STOP_TIMEOUT_SECONDS = 30.0

# Docker Desktop for Windows is a documented case of "on PATH for an
# interactive shell, missing from PATH for a process that shell spawns" --
# the installer updates the registry-level PATH, which an already-running
# shell's own environment doesn't always pick up consistently for its
# children. shutil.which() is tried first; this is a fallback, not the
# primary lookup.
_WINDOWS_DEFAULT_DOCKER_PATH = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"


def _docker_executable() -> str:
    found = shutil.which("docker")
    if found:
        return found
    if platform.system() == "Windows" and Path(_WINDOWS_DEFAULT_DOCKER_PATH).exists():
        return _WINDOWS_DEFAULT_DOCKER_PATH
    return "docker"  # let the subprocess call fail honestly if this guess is also wrong


class DockerUnavailableError(RuntimeError):
    pass


def docker_available() -> bool:
    try:
        result = subprocess.run(
            [_docker_executable(), "info"], capture_output=True, text=True, timeout=_DOCKER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _run_docker(*args: str, timeout: float) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run([_docker_executable(), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DockerUnavailableError(f"docker {' '.join(args)} failed to run: {exc}") from exc
    if result.returncode != 0:
        raise DockerUnavailableError(f"docker {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}")
    return result


def build_image(context_dir: str, tag: str) -> None:
    _run_docker("build", "-t", tag, context_dir, timeout=_BUILD_TIMEOUT_SECONDS)


def run_container(image_tag: str, container_port: int, *, name: str) -> None:
    _run_docker(
        "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1::{container_port}", image_tag,
        timeout=_RUN_TIMEOUT_SECONDS,
    )


def container_host_port(name: str, container_port: int) -> int:
    result = _run_docker("port", name, f"{container_port}/tcp", timeout=_DOCKER_TIMEOUT_SECONDS)
    # Output looks like "127.0.0.1:54321" (one line per published binding).
    line = result.stdout.strip().splitlines()[0]
    return int(line.rsplit(":", 1)[-1])


def stop_container(name: str) -> None:
    # Best-effort: a container that never started, or already exited, isn't
    # a reason to raise out of a teardown path.
    try:
        subprocess.run(
            [_docker_executable(), "rm", "-f", name], capture_output=True, text=True, timeout=_STOP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass  # best-effort: a teardown path must never itself raise


def remove_image(tag: str) -> None:
    # Best-effort, same reasoning as stop_container: only ever called for an
    # image this module itself built (never a caller-supplied image_tag,
    # whose lifecycle the caller owns), so a failure here just leaves a
    # dangling image behind rather than losing anything a caller needs.
    try:
        subprocess.run(
            [_docker_executable(), "rmi", "-f", tag], capture_output=True, text=True, timeout=_STOP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def wait_until_ready(url: str, *, timeout_s: float = 20.0, poll_interval_s: float = 0.3) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            httpx.get(url, timeout=2.0)
            return
        except httpx.HTTPError as exc:
            last_error = exc
            time.sleep(poll_interval_s)
    raise TimeoutError(f"{url} did not become ready within {timeout_s}s: {last_error}")


@dataclass
class RunningContainer:
    name: str
    base_url: str
    host_port: int


class ManagedDockerEnvironment:
    """Build (if needed) + run + wait-for-ready + guaranteed teardown for
    one containerized target app, for the lifetime of a `with` block.

    `image_tag=None` (the default) rebuilds from `context_dir` every time --
    correct for a target under active development, at the cost of a build
    each run; pass an explicit `image_tag` for an already-built image to
    skip the rebuild.
    """

    def __init__(
        self,
        context_dir: str,
        container_port: int,
        *,
        image_tag: str | None = None,
        ready_path: str = "/",
        ready_timeout_s: float = 20.0,
    ):
        if not docker_available():
            raise DockerUnavailableError("Docker daemon is not reachable (is Docker running?)")
        self._context_dir = context_dir
        self._container_port = container_port
        self._image_tag = image_tag or f"veriforge-env-{uuid.uuid4().hex[:8]}"
        self._built_here = image_tag is None
        self._name = f"veriforge-env-{uuid.uuid4().hex[:8]}"
        self._ready_path = ready_path
        self._ready_timeout_s = ready_timeout_s

    def __enter__(self) -> RunningContainer:
        if self._built_here:
            build_image(self._context_dir, self._image_tag)
        run_container(self._image_tag, self._container_port, name=self._name)
        try:
            host_port = container_host_port(self._name, self._container_port)
            base_url = f"http://127.0.0.1:{host_port}"
            wait_until_ready(base_url + self._ready_path, timeout_s=self._ready_timeout_s)
        except Exception:
            stop_container(self._name)
            if self._built_here:
                remove_image(self._image_tag)
            raise
        return RunningContainer(name=self._name, base_url=base_url, host_port=host_port)

    def __exit__(self, *exc_info) -> None:
        stop_container(self._name)
        if self._built_here:
            remove_image(self._image_tag)
