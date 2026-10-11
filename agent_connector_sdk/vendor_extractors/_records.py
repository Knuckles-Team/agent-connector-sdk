"""Shared private record helpers for the vendor extractors."""

from __future__ import annotations

from typing import Any


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _first(record: Any, *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = _get(record, key)
        if value is not None and value != "":
            return value
    return None


def _invoke(method: Any) -> Any:
    """Call ``method()``; on ``TypeError`` retry with an empty params dict."""
    try:
        return method()
    except TypeError:
        return method({})


def _as_list(value: Any) -> list[Any]:
    """Coerce a scalar/None/list relation field into a clean list."""
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [item for item in value if item]
    return [value]


def _call_list(client: Any, name: str, keys: tuple[str, ...]) -> list[Any]:
    """Call a client list-method if present, unwrapping the first truthy key."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = _invoke(method)
    except Exception:
        return []
    if isinstance(result, dict):
        result = next((result[k] for k in keys if result.get(k)), [])
    return list(result) if result else []


def _safe_call(client: Any, name: str, *args: Any) -> Any:
    """Call ``client.<name>(*args)`` if callable; ``None`` when absent or failing."""
    method = getattr(client, name, None)
    try:
        return method(*args) if callable(method) else None
    except Exception:
        return None


def _props(**fields: Any) -> dict[str, Any]:
    """Drop ``None``-valued fields."""
    return {key: value for key, value in fields.items() if value is not None}
