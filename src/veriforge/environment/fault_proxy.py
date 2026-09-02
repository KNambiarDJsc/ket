"""Fault-Injecting Proxy (Phase 14 Environment Engineering, spec §9/§22):
a real HTTP reverse proxy sitting in front of a live target application, so
an Executor can exercise latency, timeout, service-failure, duplicate-
event, and stale-state conditions against a genuine backend -- the
environment itself becomes a controllable, mutable subject (the Google
EnvHarness prior art this design cites), not just a fixed target assumed
to behave.

Five fault types, each independently configurable per request path:
  latency_ms      -- every forwarded request sleeps this long first.
  timeout_paths   -- sleeps `timeout_delay_s` before still answering, long
                      enough that a client with a normal timeout gives up
                      first. Answering eventually (not hanging forever) is
                      deliberate: the point is to make a *client* observe a
                      timeout in a bounded test, not to hang the proxy.
  failure_rate    -- every Nth request to the path gets a 503 instead of
                      being forwarded at all (N = round(1/failure_rate),
                      so 0.5 means every 2nd request -- deterministic, not
                      a coin flip, so a test can assert an exact count).
  duplicate_paths -- forwarded to the backend TWICE (the first response is
                      discarded); simulates a flaky-network retry that
                      actually reaches the server twice, e.g. to test
                      whether a POST is safe against a duplicated create.
  stale_paths     -- the FIRST successful response for the path is cached
                      and replayed on every later request, even after the
                      backend's real state has moved on -- simulates a
                      caching layer serving stale data.

Single-threaded (`HTTPServer`, not `ThreadingHTTPServer`) on purpose,
matching the example apps' own simplicity: this project's fault scenarios
are about sequencing (before/after, once/twice), not concurrent request
races -- that's a genuinely different testing area (Phase 15's Security +
Concurrency engine) with its own environment needs, not this proxy's job.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import httpx


@dataclass
class FaultConfig:
    latency_ms: int = 0
    failure_rate: float = 0.0
    timeout_paths: set[str] = field(default_factory=set)
    timeout_delay_s: float = 5.0
    duplicate_paths: set[str] = field(default_factory=set)
    stale_paths: set[str] = field(default_factory=set)


class FaultInjectingProxy:
    def __init__(self, backend_base_url: str, faults: FaultConfig):
        self._backend = backend_base_url.rstrip("/")
        self._faults = faults
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self._stale_cache: dict[str, tuple[int, dict, bytes]] = {}
        self._request_counts: dict[str, int] = {}

    def start(self, port: int = 0) -> str:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002 - silence default stderr logging
                pass

            def _dispatch(self) -> None:
                proxy._handle_request(self)

            do_GET = do_POST = do_PUT = do_DELETE = _dispatch

        # 127.0.0.1, not "localhost": on Windows, resolving "localhost" can
        # try IPv6 first and fall back to IPv4 after a multi-second delay --
        # harmless for correctness but fatal to this module's own
        # latency-fault tests, which assert on real elapsed time.
        self._server = HTTPServer(("127.0.0.1", port), Handler)
        actual_port = self._server.server_address[1]
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{actual_port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _forward(self, method: str, path: str, headers: dict, body: bytes | None) -> httpx.Response:
        return httpx.request(method, self._backend + path, headers=headers, content=body, timeout=10.0)

    def _should_fail(self, path: str) -> bool:
        if self._faults.failure_rate <= 0:
            return False
        self._request_counts[path] = self._request_counts.get(path, 0) + 1
        every_nth = round(1 / self._faults.failure_rate)
        return self._request_counts[path] % every_nth == 0

    def _handle_request(self, handler: BaseHTTPRequestHandler) -> None:
        method, path = handler.command, handler.path
        length = int(handler.headers.get("Content-Length", 0) or 0)
        body = handler.rfile.read(length) if length else None
        headers = {k: v for k, v in handler.headers.items() if k.lower() not in ("host", "content-length")}

        if path in self._faults.timeout_paths:
            time.sleep(self._faults.timeout_delay_s)

        if self._should_fail(path):
            self._send_json(handler, 503, {"error": "injected failure"})
            return

        if self._faults.latency_ms:
            time.sleep(self._faults.latency_ms / 1000)

        if path in self._faults.stale_paths and path in self._stale_cache:
            status, resp_headers, resp_body = self._stale_cache[path]
            self._send_raw(handler, status, resp_headers, resp_body)
            return

        if path in self._faults.duplicate_paths:
            self._forward(method, path, headers, body)  # reaches the backend; response discarded

        response = self._forward(method, path, headers, body)
        if path in self._faults.stale_paths:
            self._stale_cache[path] = (response.status_code, dict(response.headers), response.content)
        self._send_raw(handler, response.status_code, dict(response.headers), response.content)

    _DROPPED_RESPONSE_HEADERS = ("content-length", "transfer-encoding", "connection")

    def _send_raw(self, handler: BaseHTTPRequestHandler, status: int, headers: dict, body: bytes) -> None:
        handler.send_response(status)
        for key, value in headers.items():
            if key.lower() in self._DROPPED_RESPONSE_HEADERS:
                continue
            handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _send_json(self, handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
        self._send_raw(handler, status, {"Content-Type": "application/json"}, json.dumps(body).encode("utf-8"))
