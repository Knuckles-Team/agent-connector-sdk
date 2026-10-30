"""Validate bounded bookmark export records without fetching URLs."""

from __future__ import annotations

import json
from typing import Any

from scion_sdk.adapters.bookmark_models import BookmarkReadError

_MAX_RECORD_BYTES = 65_536
_MAX_RECORDS = 10_000


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BookmarkReadError("invalid_content")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise BookmarkReadError("invalid_content")


def _parse(data: bytes) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(
            data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (UnicodeError, ValueError, RecursionError):
        raise BookmarkReadError("invalid_content") from None
    if isinstance(decoded, list):
        records = decoded
    elif isinstance(decoded, dict) and set(decoded) == {"bookmarks"}:
        records = decoded["bookmarks"]
    else:
        raise BookmarkReadError("unsupported_type")
    if not isinstance(records, list):
        raise BookmarkReadError("invalid_content")
    if len(records) > _MAX_RECORDS:
        raise BookmarkReadError("limit_exceeded")
    if any(not isinstance(row, dict) for row in records):
        raise BookmarkReadError("invalid_content")
    return records


def _validate_entities(raw: dict[str, Any]) -> None:
    """Refuse malformed supported metadata instead of silently dropping it."""
    legacy = raw.get("legacy")
    if legacy is not None and not isinstance(legacy, dict):
        raise BookmarkReadError("invalid_content")
    for entities in (raw.get("entities"), (legacy or {}).get("entities")):
        if entities is None:
            continue
        if not isinstance(entities, dict):
            raise BookmarkReadError("invalid_content")
        _validate_group(entities)


def _invalid_entry(entry: Any, fields: tuple[str, ...]) -> bool:
    if not isinstance(entry, dict):
        return True
    return any(
        field in entry and not isinstance(entry[field], str) for field in fields
    ) or not any(entry.get(field) for field in fields)


def _validate_group(entities: dict[str, Any]) -> None:
    for kind, fields in (
        ("hashtags", ("tag", "text")),
        ("user_mentions", ("screen_name", "username")),
        ("urls", ("expanded_url", "url")),
    ):
        entries = entities.get(kind)
        if entries is None:
            continue
        if not isinstance(entries, list) or any(
            _invalid_entry(entry, fields) for entry in entries
        ):
            raise BookmarkReadError("invalid_content")


def _validated_record(raw: dict[str, Any]) -> tuple[str, str, bytes]:
    try:
        encoded = json.dumps(
            raw,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError, RecursionError):
        raise BookmarkReadError("invalid_content") from None
    if len(encoded) > _MAX_RECORD_BYTES:
        raise BookmarkReadError("limit_exceeded")
    identity, text = raw.get("id"), raw.get("text")
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 256:
        raise BookmarkReadError("invalid_content")
    if not isinstance(text, str) or len(text) > 65_536:
        raise BookmarkReadError("invalid_content")
    _validate_entities(raw)
    return identity, text, encoded
