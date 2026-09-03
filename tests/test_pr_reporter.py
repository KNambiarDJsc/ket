"""Phase 20: format_pr_comment is a pure function, tested directly.
post_pr_comment makes a real httpx.post call -- tested against a mocked
transport here, never a real GitHub API call. This project has never
posted a real PR comment in its own development; see ci/pr_reporter.py's
own module docstring for why that's the honest, intentional state."""
import httpx
import pytest

from veriforge.ci.pr_reporter import (
    InvalidPrTargetError,
    format_pr_comment,
    parse_pr_target,
    post_pr_comment,
)
from veriforge.domain.enums import FailureCategory, Verdict
from veriforge.domain.models import Finding


# ---- parse_pr_target ----

def test_parse_pr_target_extracts_owner_repo_and_number():
    assert parse_pr_target("KNambiarDJsc/ket#42") == ("KNambiarDJsc", "ket", 42)


def test_parse_pr_target_rejects_malformed_input():
    with pytest.raises(InvalidPrTargetError):
        parse_pr_target("not-a-valid-target")


# ---- format_pr_comment ----

def test_format_pr_comment_reports_fail_with_findings():
    finding = Finding(
        project_id="p", summary="members can delete projects",
        category=FailureCategory.SECURITY_FINDING, confidence=0.9, reproduced=True,
    )
    body = format_pr_comment(job_id="job_1", repo_display="example-app", verdict=Verdict.FAIL.value, findings=[finding])

    assert "❌" in body
    assert "FAIL" in body
    assert "SECURITY_FINDING" in body
    assert "0.90" in body
    assert "reproduced" in body
    assert "members can delete projects" in body
    assert "job_1" in body


def test_format_pr_comment_reports_pass_with_no_findings():
    body = format_pr_comment(job_id="job_2", repo_display="example-app", verdict=Verdict.PASS.value, findings=[])
    assert "✅" in body
    assert "PASS" in body
    assert "Findings" not in body  # no findings section when there are none


def test_format_pr_comment_reports_no_executable_requirement():
    body = format_pr_comment(job_id="job_3", repo_display="example-app", verdict=None, findings=[])
    assert "No executable requirement" in body


# ---- post_pr_comment, against a mocked transport only ----

def test_post_pr_comment_sends_the_expected_request(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read()
        return httpx.Response(201, json={"id": 1})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Client(transport=transport).post(url, **kwargs))

    post_pr_comment(owner="KNambiarDJsc", repo="ket", pr_number=42, body="hello", token="secret-token")

    assert captured["url"] == "https://api.github.com/repos/KNambiarDJsc/ket/issues/42/comments"
    assert captured["auth"] == "Bearer secret-token"
    assert b"hello" in captured["body"]


def test_post_pr_comment_raises_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Client(transport=transport).post(url, **kwargs))

    with pytest.raises(httpx.HTTPStatusError):
        post_pr_comment(owner="o", repo="r", pr_number=1, body="x", token="t")
