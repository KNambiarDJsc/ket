"""Tiny example app for exercising VeriForge end-to-end.

Deliberately dependency-free (stdlib http.server only) so `python app.py`
works with nothing installed. Implements just enough of the "members cannot
delete projects" example from the VeriForge spec (§5/§7) to give later
phases (Explorer, Oracle, security hypothesis engine) a real target with a
genuine authorization bug baked in on purpose (see requirements.md).

GET /ui is a minimal HTML frontend (fetch() calls against the JSON API
below) added for Phase 4's browser explorer — the JSON API alone has
nothing for Playwright to click through.
"""
from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

PROJECTS: dict[str, dict] = {}

UI_HTML = """<!doctype html>
<html>
<head><title>VeriForge Example App</title></head>
<body>
  <h1>Projects</h1>
  <ul id="project-list"></ul>
  <button id="create-btn">Create Project</button>
  <script>
    async function refresh() {
      const res = await fetch("/projects");
      const data = await res.json();
      const list = document.getElementById("project-list");
      list.innerHTML = "";
      for (const p of data.projects) {
        const li = document.createElement("li");
        li.textContent = p.name + " ";
        const del = document.createElement("button");
        del.textContent = "Delete";
        del.dataset.id = p.id;
        del.onclick = async () => {
          await fetch("/projects/" + p.id, { method: "DELETE" });
          refresh();
        };
        li.appendChild(del);
        list.appendChild(li);
      }
    }
    document.getElementById("create-btn").onclick = async () => {
      await fetch("/projects", { method: "POST" });
      refresh();
    };
    refresh();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _role(self) -> str:
        return self.headers.get("X-Role", "member")

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/":
            self._send_json(200, {"service": "veriforge-example-app", "status": "ok"})
        elif self.path == "/ui":
            self._send_html(200, UI_HTML)
        elif self.path == "/projects":
            self._send_json(200, {"projects": list(PROJECTS.values())})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path == "/projects":
            project_id = uuid.uuid4().hex[:8]
            PROJECTS[project_id] = {"id": project_id, "name": f"project-{project_id}"}
            self._send_json(201, PROJECTS[project_id])
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        if self.path.startswith("/projects/"):
            project_id = self.path.rsplit("/", 1)[-1]
            # INTENTIONAL BUG: this endpoint does not actually check X-Role,
            # so a "member" can delete a project, violating the requirement
            # "Members cannot delete projects." This exists on purpose as a
            # fixture for later phases' authorization-testing skill.
            if project_id in PROJECTS:
                del PROJECTS[project_id]
                self._send_json(200, {"deleted": project_id})
            else:
                self._send_json(404, {"error": "not found"})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):  # noqa: A002 - silence default stderr logging
        pass


def main(port: int = 8000) -> None:
    server = HTTPServer(("localhost", port), Handler)
    print(f"veriforge example-app listening on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
