"""Second example app for Phase 11 (Database Observation): a real SQLite-
backed service, so the Oracle can compare what the API claims against what
the database actually holds -- something the dict-backed `example-app`
can't exercise, since it has no persistence layer independent of the API
itself.

Deliberately dependency-free (stdlib http.server + sqlite3 only) so
`python app.py` works with nothing installed, matching examples/example-app.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")


def init_db(db_path: str = DB_PATH) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)"
        )
        conn.commit()
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/":
            self._send_json(200, {"service": "veriforge-example-db-app", "status": "ok"})
        elif self.path == "/projects":
            conn = self._conn()
            try:
                # Only non-deleted rows are ever shown through the API -- this
                # is exactly what makes the DELETE bug below invisible to an
                # API-only state check (Phase 6's follow-up GET).
                rows = conn.execute("SELECT id, name FROM projects WHERE deleted = 0").fetchall()
            finally:
                conn.close()
            self._send_json(200, {"projects": [dict(r) for r in rows]})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path == "/projects":
            project_id = uuid.uuid4().hex[:8]
            name = f"project-{project_id}"
            conn = self._conn()
            try:
                conn.execute("INSERT INTO projects (id, name, deleted) VALUES (?, ?, 0)", (project_id, name))
                conn.commit()
            finally:
                conn.close()
            self._send_json(201, {"id": project_id, "name": name})
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        if self.path.startswith("/projects/"):
            project_id = self.path.rsplit("/", 1)[-1]
            conn = self._conn()
            try:
                existing = conn.execute("SELECT id FROM projects WHERE id = ? AND deleted = 0", (project_id,)).fetchone()
                if existing is None:
                    self._send_json(404, {"error": "not found"})
                    return
                # INTENTIONAL BUG: this only flips a `deleted` flag -- the row
                # is never actually removed from the database. The API layer
                # (GET /projects above) filters deleted=0, so through the API
                # the project genuinely looks gone: a follow-up GET (Phase 6's
                # Level-3 state check) reports "not present" and would judge
                # this PASS. Only a direct database read can see the row is
                # still physically there, which is exactly the gap Phase 11's
                # DB-state-comparison Oracle exists to close.
                conn.execute("UPDATE projects SET deleted = 1 WHERE id = ?", (project_id,))
                conn.commit()
                self._send_json(200, {"deleted": project_id})
            finally:
                conn.close()
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):  # noqa: A002 - silence default stderr logging
        pass


def main(port: int = 8001) -> None:
    init_db()
    # 0.0.0.0, not "localhost": this is the entry point Docker's CMD runs
    # (Phase 14) as well as direct `python app.py`. A server bound only to
    # a container's own loopback is unreachable through Docker's -p port
    # publishing -- a well-documented Docker networking gotcha, not a
    # Docker bug. The test fixtures construct HTTPServer directly (bound to
    # "localhost") and never call main(), so this doesn't affect them.
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"veriforge example-db-app listening on http://0.0.0.0:{port} (db: {DB_PATH})")
    server.serve_forever()


if __name__ == "__main__":
    main()
