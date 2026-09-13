"""A scripted local HTTP(S) server for client tests and the conformance kit.

Each request takes the next queued :class:`ScriptedResponse`; the request is
recorded in :attr:`ScriptedHttpServer.requests`. It binds to loopback on an
ephemeral port and serves from a daemon thread.
"""

from __future__ import annotations

import ssl
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = ["ReceivedRequest", "ScriptedHttpServer", "ScriptedResponse"]


@dataclass(frozen=True)
class ScriptedResponse:
    """One response to serve, after ``delay`` seconds."""

    status: int = 200
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass(frozen=True)
class ReceivedRequest:
    """One request the server received."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class _Handler(BaseHTTPRequestHandler):
    server: _ScriptServer

    def _serve(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {name.lower(): value for name, value in self.headers.items()}
        self.server.owner.requests.append(
            ReceivedRequest(self.command, self.path, headers, body)
        )
        scripted = self.server.owner.next_response()
        time.sleep(scripted.delay)
        self.send_response(scripted.status)
        for name, value in scripted.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(scripted.body)))
        self.end_headers()
        self.wfile.write(scripted.body)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _serve

    def log_message(self, format: str, *args: object) -> None:
        """Record the access log line instead of writing it to stderr."""
        self.server.owner.log_lines.append(format % args)


class _ScriptServer(ThreadingHTTPServer):
    daemon_threads = True
    owner: ScriptedHttpServer

    def handle_error(self, *_request_and_address: object) -> None:
        """Count a request the client abandoned (a timeout test) instead of printing it."""
        self.owner.abandoned += 1


class ScriptedHttpServer:
    """Serves queued responses on ``127.0.0.1``; use as a context manager."""

    def __init__(
        self, *responses: ScriptedResponse, ssl_context: ssl.SSLContext | None = None
    ) -> None:
        self.requests: list[ReceivedRequest] = []
        #: Requests whose client disconnected before the response was written.
        self.abandoned = 0
        #: The server's access log lines.
        self.log_lines: list[str] = []
        self._queue: deque[ScriptedResponse] = deque(responses)
        self._lock = threading.Lock()
        self._server = _ScriptServer(("127.0.0.1", 0), _Handler)
        self._server.owner = self
        self._scheme = "http"
        if ssl_context is not None:
            self._server.socket = ssl_context.wrap_socket(
                self._server.socket, server_side=True
            )
            self._scheme = "https"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """``http(s)://127.0.0.1:<port>``."""
        return f"{self._scheme}://127.0.0.1:{self._server.server_address[1]}"

    def enqueue(self, *responses: ScriptedResponse) -> None:
        """Queue more responses."""
        with self._lock:
            self._queue.extend(responses)

    def next_response(self) -> ScriptedResponse:
        """The next queued response; ``599`` when the script is exhausted."""
        with self._lock:
            return (
                self._queue.popleft() if self._queue else ScriptedResponse(status=599)
            )

    def __enter__(self) -> ScriptedHttpServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
