"""Connector-owned decoding for generic Kafka and NATS event payloads."""

from __future__ import annotations

import json
from typing import Any


def decode_stream_payload(value: Any) -> dict[str, Any]:
    """Decode a generic stream event, preserving the existing raw fallback."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return {"raw": repr(value)}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return {"raw": value}
        if not isinstance(decoded, dict):
            raise ValueError("stream event JSON must be an object")
        return decoded
    return value if isinstance(value, dict) else {"raw": str(value)}


def decode_json_value_or_none(value: Any) -> Any:
    """Decode one JSON wire value, returning None when it is invalid or absent."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return None
    return value


def decode_json_object_or_none(value: Any) -> dict[str, Any] | None:
    """Decode a strict object event, returning None for malformed wire input.

    This is for fire-and-forget streams that account for malformed records
    explicitly instead of placing raw text in a graph event envelope.
    """
    decoded = decode_json_value_or_none(value)
    return decoded if isinstance(decoded, dict) else None
