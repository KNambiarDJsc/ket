from veriforge.cartography.python_ast import analyze_repository


def test_flask_style_decorators_detected(tmp_path):
    (tmp_path / "app.py").write_text(
        """
from flask import Flask
app = Flask(__name__)

@app.get("/items")
def list_items():
    return []

@app.route("/items/<id>", methods=["DELETE"])
def delete_item(id):
    return "ok"
""",
        encoding="utf-8",
    )

    analysis = analyze_repository(tmp_path)
    methods_paths = {(e.method, e.path) for e in analysis.endpoints}
    assert ("GET", "/items") in methods_paths
    assert ("DELETE", "/items/<id>") in methods_paths


def test_django_style_path_calls_detected(tmp_path):
    (tmp_path / "urls.py").write_text(
        """
from django.urls import path

urlpatterns = [
    path("projects/", views.list_projects),
    path("projects/<int:pk>/", views.delete_project),
]
""",
        encoding="utf-8",
    )

    analysis = analyze_repository(tmp_path)
    paths = {e.path for e in analysis.endpoints}
    assert "projects/" in paths
    assert "projects/<int:pk>/" in paths


def test_stdlib_http_server_style_detected_with_role_hint(tmp_path):
    (tmp_path / "app.py").write_text(
        """
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def _role(self):
        return self.headers.get("X-Role", "member")

    def do_DELETE(self):
        if self.path.startswith("/projects/"):
            pass

    def do_GET(self):
        if self.path == "/projects":
            pass
""",
        encoding="utf-8",
    )

    analysis = analyze_repository(tmp_path)
    by_method = {(e.method, e.path): e for e in analysis.endpoints}
    assert ("DELETE", "/projects/") in by_method
    assert ("GET", "/projects") in by_method
    # do_DELETE's body never references self._role()/role/permission -- the
    # AST walk is scoped to the function, so the sibling method's role
    # reference must not leak in.
    assert by_method[("DELETE", "/projects/")].mentions_role_check is False


def test_persistence_backend_detected_from_imports(tmp_path):
    (tmp_path / "db.py").write_text("import sqlalchemy\nfrom sqlalchemy.orm import Session\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    assert "sqlalchemy" in analysis.persistence_backends


def test_no_persistence_imports_means_empty_backends(tmp_path):
    (tmp_path / "app.py").write_text("PROJECTS = {}\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    assert analysis.persistence_backends == set()


def test_syntax_error_file_does_not_crash_the_scan(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("@app.get('/x')\ndef f():\n    pass\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    assert any(e.path == "/x" for e in analysis.endpoints)


def test_nonexistent_repo_returns_empty_analysis(tmp_path):
    analysis = analyze_repository(tmp_path / "missing")
    assert analysis.endpoints == []
    assert analysis.persistence_backends == set()
