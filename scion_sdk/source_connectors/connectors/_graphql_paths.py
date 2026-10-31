"""Dotted-path lookup helpers for the GraphQL document connector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._graphql_base import (
    _FIELD_NAME_RE,
    _FIELD_PATH_RE,
)


def _dig(value: Any, path: str, default: Any = None) -> Any:
    current = value
    for part in (segment for segment in path.split(".") if segment):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _is_invalid_next_cursor(next_cursor_text: str, seen_cursors: set[str]) -> bool:
    return (
        not next_cursor_text
        or next_cursor_text != next_cursor_text.strip()
        or len(next_cursor_text.encode("utf-8")) > 4_096
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in next_cursor_text
        )
        or next_cursor_text in seen_cursors
    )


def _dig_resolve_segment(current: list[Any], part: str) -> list[Any]:
    """Resolve one dotted-path segment across all in-flight items."""
    resolved: list[Any] = []
    for item in current:
        values = item if isinstance(item, list) else [item]
        for candidate in values:
            if isinstance(candidate, Mapping) and part in candidate:
                resolved.append(candidate[part])
    return resolved


def _dig_flatten(current: list[Any]) -> list[Any]:
    """Flatten one level of list nesting produced by fan-out resolution."""
    flattened: list[Any] = []
    for item in current:
        if isinstance(item, list):
            flattened.extend(item)
        else:
            flattened.append(item)
    return flattened


def _dig_many(value: Any, path: str) -> list[Any]:
    """Resolve a dotted path while treating lists as bounded fan-out points."""
    current = [value]
    for part in (segment for segment in str(path or "").split(".") if segment):
        current = _dig_resolve_segment(current, part)
    return _dig_flatten(current)


def _valid_field_path(value: Any) -> bool:
    rendered = str(value or "")
    return len(rendered.encode("utf-8")) <= 512 and bool(
        _FIELD_PATH_RE.fullmatch(rendered)
    )


def _valid_field_name(value: Any) -> bool:
    return bool(_FIELD_NAME_RE.fullmatch(str(value or "")))
