"""A loopback HTTP server answering fixed responses by path."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scion_sdk.testing._http_script import ScriptedResponse, _send_scripted


@dataclass(frozen=True)
class RoutedRequest:
    """One request a :class:`RoutedHttpServer` answered, with its arrival time."""

    path: str
    at: float
    user_agent: str


class _RoutedHandler(BaseHTTPRequestHandler):
    server: _RoutedServer

    def do_GET(self) -> None:
        owner = self.server.owner
        path = self.path.split("?", 1)[0]
        owner.requests.append(
            RoutedRequest(
                path=path,
                at=time.monotonic(),
                user_agent=self.headers.get("user-agent", ""),
            )
        )
        response = owner.routes.get(
            path, ScriptedResponse(status=404, body=b"not found")
        )
        _send_scripted(self, response)

    def log_message(self, *_args: object) -> None:
        return


class _RoutedServer(ThreadingHTTPServer):
    owner: RoutedHttpServer


class RoutedHttpServer:
    """A loopback HTTP server answering fixed responses by path.

    Every request is recorded in :attr:`requests` with its arrival time, so a
    test can check what a client fetched and how far apart.
    """

    def __init__(self, routes: Mapping[str, ScriptedResponse]) -> None:
        self.routes = dict(routes)
        self.requests: list[RoutedRequest] = []
        self._server = _RoutedServer(("127.0.0.1", 0), _RoutedHandler)
        self._server.owner = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> RoutedHttpServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    def served(self, path: str) -> list[RoutedRequest]:
        return [request for request in self.requests if request.path == path]
