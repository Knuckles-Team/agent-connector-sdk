"""Absolute deadlines for governed A2A discovery."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_connector_sdk.vendor_extractors import a2a_discovery as discovery


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R047.2")
def test_trickling_card_cannot_exceed_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "20")
            self.end_headers()
            try:
                for byte in b'{"name":"slow-card"}':
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.08)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    monkeypatch.setattr(discovery, "DEFAULT_DISCOVERY_TIMEOUT_SECONDS", 0.25)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        started = time.monotonic()
        result = discovery.discover_agent_card(url, allow_loopback=True)
        elapsed = time.monotonic() - started
        assert result == discovery.AgentCardRefused("not_found")
        assert elapsed < 1.0
        assert discovery._cached(url, None) is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R047.2")
def test_stalled_dns_is_bounded_and_cannot_cache_late_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def stalled_resolver(*args: object, **kwargs: object) -> list[object]:
        entered.set()
        release.wait(3)
        finished.set()
        return []

    monkeypatch.setattr(discovery, "DEFAULT_DISCOVERY_TIMEOUT_SECONDS", 0.25)
    monkeypatch.setattr(socket, "getaddrinfo", stalled_resolver)
    url = "https://deadline-test.example"
    try:
        started = time.monotonic()
        result = discovery.discover_agent_card(url)
        elapsed = time.monotonic() - started
        assert entered.is_set()
        assert not finished.is_set()
        assert result == discovery.AgentCardRefused("not_found")
        assert elapsed < 1.0
    finally:
        release.set()
    assert finished.wait(2)
    assert discovery._cached(url, None) is None
