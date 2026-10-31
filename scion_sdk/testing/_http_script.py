"""Response and request records shared by the scripted and routed HTTP servers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler


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


def _send_scripted(handler: BaseHTTPRequestHandler, response: ScriptedResponse) -> None:
    """Write ``response`` (status, headers, length-prefixed body) to ``handler``."""
    handler.send_response(response.status)
    for name, value in response.headers.items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(response.body)))
    handler.end_headers()
    handler.wfile.write(response.body)
