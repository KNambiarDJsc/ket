"""Minimal .env loader.

Deliberately not a dependency on python-dotenv for a handful of KEY=VALUE
lines — matches this project's general preference for no infrastructure
before it's needed. Real environment variables always win over `.env` file
values (standard dotenv semantics), so `VERIFORGE_FOO=x ./run` still
overrides whatever `.env` says.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_if_present(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
