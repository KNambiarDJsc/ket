"""Database engine/session setup.

Local-first default: SQLite file under the project's .veriforge/ directory.
This is a deliberate deviation from the spec's "Postgres schema" for phase 1 —
running fully local (alongside local Ollama inference) means not requiring
Docker/Postgres just to run a job. The schema uses SQLAlchemy Core, so
pointing VERIFORGE_DB_URL at a real Postgres instance later is a one-line
change, not a rewrite.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def default_db_path(base_dir: str | Path = ".") -> Path:
    veriforge_dir = Path(base_dir) / ".veriforge"
    veriforge_dir.mkdir(parents=True, exist_ok=True)
    return veriforge_dir / "veriforge.db"


def get_db_url(base_dir: str | Path = ".") -> str:
    env_url = os.environ.get("VERIFORGE_DB_URL")
    if env_url:
        return env_url
    return f"sqlite:///{default_db_path(base_dir).as_posix()}"


def get_engine(base_dir: str | Path = ".", *, echo: bool = False) -> Engine:
    global _engine
    if _engine is None:
        url = get_db_url(base_dir)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, echo=echo, connect_args=connect_args)
    return _engine


def get_session_factory(base_dir: str | Path = ".") -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(base_dir), expire_on_commit=False)
    return _SessionLocal


def get_session(base_dir: str | Path = ".") -> Session:
    return get_session_factory(base_dir)()


def reset_engine_cache() -> None:
    """Used by tests to force a fresh engine/session against a new DB path."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
