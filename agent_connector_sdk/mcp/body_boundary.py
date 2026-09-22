"""Bound and replay an HTTP request body before application code sees it."""

from __future__ import annotations

from typing import Any, cast

import anyio

from agent_connector_sdk.mcp.http_boundary import _header_values, _json_response


class _BodyBoundaryError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _BoundedRequestBodyMiddleware:
    def __init__(
        self,
        app: Any,
        max_bytes: int,
        read_timeout_seconds: float,
    ) -> None:
        if not 1_024 <= max_bytes <= 256 * 1024 * 1024:
            raise ValueError("request body limit is outside the safe range")
        if not 1.0 <= read_timeout_seconds <= 300.0:
            raise ValueError("request body timeout is outside the safe range")
        self.app = app
        self.max_bytes = max_bytes
        self.read_timeout_seconds = read_timeout_seconds

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        try:
            _validate_declared_length(scope, self.max_bytes)
            buffered, disconnected = await self._read_body_with_timeout(receive)
        except _BodyBoundaryError as exc:
            await _json_response(send, exc.status, exc.message)
            return
        await self.app(scope, _replay_receive(buffered, disconnected, receive), send)

    async def _read_body_with_timeout(self, receive: Any) -> tuple[bytes, bool]:
        try:
            with anyio.fail_after(self.read_timeout_seconds):
                return await _read_body(receive, self.max_bytes)
        except TimeoutError:
            raise _BodyBoundaryError(408, "request body timeout") from None


def _validate_declared_length(scope: Any, max_bytes: int) -> None:
    values = _header_values(scope, b"content-length")
    if len(values) > 1:
        raise _BodyBoundaryError(400, "invalid content length")
    if not values:
        return
    try:
        declared = int(values[0].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise _BodyBoundaryError(400, "invalid content length") from None
    if declared < 0:
        raise _BodyBoundaryError(400, "invalid content length")
    if declared > max_bytes:
        raise _BodyBoundaryError(413, "request body too large")


async def _read_body(receive: Any, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return b"".join(chunks), True
        body = bytes(message.get("body", b""))
        total += len(body)
        if total > max_bytes:
            raise _BodyBoundaryError(413, "request body too large")
        if body:
            chunks.append(body)
        if not message.get("more_body", False):
            return b"".join(chunks), False


def _replay_receive(buffered: bytes, disconnected: bool, receive: Any) -> Any:
    delivered = False

    async def replay() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return cast(dict[str, Any], await receive())
        delivered = True
        if disconnected:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": buffered, "more_body": False}

    return replay
