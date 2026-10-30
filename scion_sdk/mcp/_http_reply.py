"""JSON and WebSocket refusal replies for the ASGI boundary middlewares."""

from __future__ import annotations

import json
from typing import Any


async def _json_response(send: Any, status: int, error: str) -> None:
    body = json.dumps({"error": error}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _reject(scope: Any, send: Any, *, status: int, reason: str) -> None:
    if scope.get("type") == "websocket":
        await send({"type": "websocket.close", "code": 4403, "reason": reason})
        return
    await _json_response(send, status, reason)
