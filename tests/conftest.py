from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import pytest

from veriforge.storage import db as db_module
from veriforge.storage.repository import Store
from veriforge.storage.schema import create_all


@pytest.fixture
def store(tmp_path):
    db_module.reset_engine_cache()
    engine = db_module.get_engine(tmp_path)
    create_all(engine)
    session = db_module.get_session(tmp_path)
    s = Store(session)
    yield s
    s.close()
    db_module.reset_engine_cache()


EXAMPLE_APP_PATH = Path(__file__).resolve().parents[1] / "examples" / "example-app" / "app.py"


def _load_example_app_module():
    spec = importlib.util.spec_from_file_location("veriforge_example_app", EXAMPLE_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example_app_server():
    """Runs the real examples/example-app in a background thread on a free
    port, so browser/integration tests exercise the actual fixture (including
    its intentional authorization bug) instead of a synthetic stand-in."""
    module = _load_example_app_module()
    module.PROJECTS.clear()
    server = module.HTTPServer(("localhost", 0), module.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{port}"
    server.shutdown()
    thread.join(timeout=5)
