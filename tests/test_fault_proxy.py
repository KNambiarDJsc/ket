import time

import httpx
import pytest

from veriforge.environment.fault_proxy import FaultConfig, FaultInjectingProxy


def start_proxy(backend_base_url, **fault_kwargs):
    # Normalize "localhost" -> "127.0.0.1": the example_db_app_server fixture
    # yields a "localhost" URL, and on Windows that can add a multi-second
    # IPv6-then-IPv4-fallback delay per connection -- harmless for
    # correctness elsewhere, but fatal to this file's own timing assertions.
    backend_base_url = backend_base_url.replace("localhost", "127.0.0.1")
    proxy = FaultInjectingProxy(backend_base_url, FaultConfig(**fault_kwargs))
    proxy_url = proxy.start()
    return proxy, proxy_url


def test_proxy_forwards_requests_transparently(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url)
    try:
        direct = httpx.get(f"{backend_url}/")
        via_proxy = httpx.get(f"{proxy_url}/")
        assert via_proxy.status_code == direct.status_code == 200
        assert via_proxy.json() == direct.json()
    finally:
        proxy.stop()


def test_proxy_forwards_post_and_returns_real_backend_response(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url)
    try:
        resp = httpx.post(f"{proxy_url}/projects")
        assert resp.status_code == 201
        assert "id" in resp.json()
    finally:
        proxy.stop()


def test_latency_fault_adds_measurable_delay(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url, latency_ms=300)
    try:
        start = time.monotonic()
        httpx.get(f"{proxy_url}/")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.25
    finally:
        proxy.stop()


def test_no_latency_fault_is_fast(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url)
    try:
        start = time.monotonic()
        httpx.get(f"{proxy_url}/")
        elapsed = time.monotonic() - start
        assert elapsed < 0.25
    finally:
        proxy.stop()


def test_timeout_fault_causes_client_timeout(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url, timeout_paths={"/"}, timeout_delay_s=2.0)
    try:
        with pytest.raises(httpx.TimeoutException):
            httpx.get(f"{proxy_url}/", timeout=0.3)
    finally:
        proxy.stop()


def test_failure_fault_injects_503_deterministically(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url, failure_rate=0.5)
    try:
        statuses = [httpx.get(f"{proxy_url}/").status_code for _ in range(4)]
        assert statuses == [200, 503, 200, 503]
    finally:
        proxy.stop()


def test_duplicate_fault_reaches_backend_twice(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url, duplicate_paths={"/projects"})
    try:
        httpx.post(f"{proxy_url}/projects")  # one call through the proxy...
        listing = httpx.get(f"{backend_url}/projects").json()
        assert len(listing["projects"]) == 2  # ...but the backend saw it twice
    finally:
        proxy.stop()


def test_stale_fault_replays_first_response_after_backend_changes(example_db_app_server):
    backend_url, _db_path = example_db_app_server
    proxy, proxy_url = start_proxy(backend_url, stale_paths={"/projects"})
    try:
        first = httpx.get(f"{proxy_url}/projects").json()
        assert first["projects"] == []

        httpx.post(f"{backend_url}/projects")  # backend state changes directly, bypassing the proxy

        second = httpx.get(f"{proxy_url}/projects").json()
        assert second == first  # the proxy still serves the cached, now-stale response

        fresh = httpx.get(f"{backend_url}/projects").json()
        assert len(fresh["projects"]) == 1  # the backend itself did move on
    finally:
        proxy.stop()
