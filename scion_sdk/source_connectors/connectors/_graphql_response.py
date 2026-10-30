"""Bounded GraphQL transport-response decoding for the document connector."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ._graphql_base import GraphQLDocumentError, _reject_json_constant


def _require_bytes(chunk: Any) -> bytes:
    if not isinstance(chunk, bytes):
        raise TypeError("response chunk is not bytes")
    return chunk


def _iterate_chunks(iterator: Any) -> Iterator[bytes]:
    """Yield byte chunks, mapping any transport failure to a source-safe error."""
    try:
        for chunk in iterator():
            yield _require_bytes(chunk)
    except Exception:
        raise GraphQLDocumentError("GraphQL transport byte stream is invalid") from None


def _collect_bounded_iterator_bytes(iterator: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in _iterate_chunks(iterator):
        total += len(chunk)
        if total > limit:
            raise GraphQLDocumentError("GraphQL response exceeds the configured bound")
        chunks.append(chunk)
    return b"".join(chunks)


def _response_raw_bytes(response: Any, limit: int) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    iterator = getattr(response, "iter_bytes", None)
    if not callable(iterator):
        raise GraphQLDocumentError(
            "GraphQL transport must expose a bounded byte response"
        )
    return _collect_bounded_iterator_bytes(iterator, limit)


def _decode_bounded_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, RecursionError, UnicodeDecodeError):
        raise GraphQLDocumentError("GraphQL response is not valid JSON") from None
    if not isinstance(payload, dict):
        raise GraphQLDocumentError("GraphQL response is not an object")
    return payload


def _bounded_transport_payload(response: Any, limit: int) -> tuple[dict[str, Any], int]:
    """Decode a transport response only after enforcing its raw byte bound.

    Custom transports are production-capable injection points, not test-only
    shortcuts.  Requiring bytes (or a bounded byte iterator) prevents ``.json()``
    from allocating an arbitrarily large object before the connector can apply its
    configured response limit.
    """

    raw = _response_raw_bytes(response, limit)
    if len(raw) > limit:
        raise GraphQLDocumentError("GraphQL response exceeds the configured bound")
    payload = _decode_bounded_json(raw)
    return payload, len(raw)
