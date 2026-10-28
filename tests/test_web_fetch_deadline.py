"""A web source cannot evade its fetch deadline by trickling bytes."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_connector_sdk.adapters.web_fetch import fetch_page


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.55")
async def test_fetch_deadline_bounds_trickling_body() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "24")
            self.end_headers()
            try:
                for byte in b"<html>slow source</html>":
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.08)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        result = await fetch_page(
            f"http://127.0.0.1:{server.server_port}/",
            timeout=0.25,
            allowed_private_hosts=("127.0.0.1",),
        )
        elapsed = time.monotonic() - started
        assert result is None
        assert elapsed < 1.0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.55")
async def test_fetch_deadline_bounds_stalled_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def resolver(*args: object, **kwargs: object) -> list[object]:
        entered.set()
        release.wait(3)
        finished.set()
        return []

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    try:
        started = time.monotonic()
        result = await fetch_page("https://deadline-test.example/", timeout=0.25)
        elapsed = time.monotonic() - started
        assert entered.is_set()
        assert not finished.is_set()
        assert result is None
        assert elapsed < 1.0
    finally:
        release.set()
