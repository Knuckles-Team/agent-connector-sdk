"""A small loopback-bindable HTTP endpoint serving runner health.

Hand-rolled over :mod:`http.server` -- no new web framework, matching the
fleet's other hand-rolled status listeners. It runs in a background thread so
it never competes with the supervisor's anyio event loop; every response
reads :class:`~agent_connector_sdk.runner.health_state.RunnerHealth`, which the
scheduler loop and workers update from the event-loop side.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_connector_sdk.mcp.exposure import is_loopback_host
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.health_state import HealthReport, RunnerHealth

__all__ = ["DEFAULT_HEALTH_HOST", "HealthServer", "parse_health_address"]

#: A bare port binds here -- see :func:`parse_health_address`.
DEFAULT_HEALTH_HOST = "127.0.0.1"

_PORT_ONLY = re.compile(r"^\d+$")
_HOST_PORT = re.compile(r"^(?P<host>\[[^\]]+\]|[^:]+):(?P<port>\d+)$")


def parse_health_address(raw: str) -> tuple[str, int]:
    """Split a health address into ``(host, port)``.

    ``PORT`` alone binds :data:`DEFAULT_HEALTH_HOST`; ``HOST:PORT`` binds the
    given host (loopback or not -- :class:`HealthServer` enforces the policy).

    Raises:
        RunnerConfigurationError: ``raw`` is neither shape.
    """
    text = raw.strip()
    if _PORT_ONLY.match(text):
        return DEFAULT_HEALTH_HOST, int(text)
    match = _HOST_PORT.match(text)
    if match is None:
        raise RunnerConfigurationError(
            f"health address {raw!r} is not PORT or HOST:PORT"
        )
    return match.group("host").strip("[]"), int(match.group("port"))


def _handler_factory(health: RunnerHealth) -> type[BaseHTTPRequestHandler]:
    routes: dict[str, Callable[[], HealthReport]] = {
        "/health": health.liveness,
        "/health/ready": health.readiness,
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "connector-sync-health/1"

        def log_message(self, *args: object) -> None:
            # Structured runner logs (logs.py) are the real signal; a stdlib
            # access log to stderr would just be noise on every probe tick.
            return None

        def do_GET(self) -> None:  # required BaseHTTPRequestHandler override name
            report = routes.get(self.path)
            if report is None:
                self.send_response(404)
                self.end_headers()
                return
            self._respond(report())

        def _respond(self, report: HealthReport) -> None:
            payload = json.dumps(report.body).encode("utf-8")
            self.send_response(report.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


class HealthServer:
    """Serves ``/health`` and ``/health/ready`` for one :class:`RunnerHealth`.

    Args:
        health: The state to report.
        host: Bind host; refused unless loopback or ``allow_non_loopback``.
        port: Bind port (``0`` picks a free port, read back via ``address``).
        allow_non_loopback: Explicit opt-in for a non-loopback ``host`` -- a
            Kubernetes ``httpGet`` probe reaches the pod IP, not loopback, so
            a real cluster deployment must pass this deliberately.

    Raises:
        RunnerConfigurationError: ``host`` is not loopback and
            ``allow_non_loopback`` was not set.
    """

    def __init__(
        self,
        health: RunnerHealth,
        *,
        host: str,
        port: int,
        allow_non_loopback: bool = False,
    ) -> None:
        if not is_loopback_host(host) and not allow_non_loopback:
            raise RunnerConfigurationError(
                f"health address {host!r} is not loopback; pass "
                "allow_non_loopback to bind it (e.g. a Kubernetes pod IP)"
            )
        self._server = ThreadingHTTPServer((host, port), _handler_factory(health))
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        """The actually-bound ``(host, port)`` (resolves a requested ``0``)."""
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        """Serve in a daemon background thread."""
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="connector-sync-health",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving, if started, and release the socket."""
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5.0)
        self._server.server_close()
