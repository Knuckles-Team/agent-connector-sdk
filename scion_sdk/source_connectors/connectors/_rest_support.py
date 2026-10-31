"""Field lookup, cursor coercion and fetcher construction for the REST source."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..http_safety import safe_get_json

# A fetch returns the decoded JSON for a (url, params) request.
JsonFetchFn = Callable[[str, dict[str, Any]], Any]


def _dig(record: dict[str, Any], dotted: str) -> Any:
    """Resolve a dotted path (``a.b.c``) within a nested dict; ``None`` if absent."""
    cur: Any = record
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _make_httpx_fetch(
    transport: Any = None,
    headers: dict[str, str] | None = None,
    *,
    allowed_private_hosts: list[str] | None = None,
    allowed_redirect_hosts: list[str] | None = None,
    max_response_bytes: int = 10 * 1024 * 1024,
) -> JsonFetchFn:
    """Build a bounded, redirect-validating JSON fetcher."""

    def _fetch(url: str, params: dict[str, Any]) -> Any:
        return safe_get_json(
            url,
            params=params,
            headers=headers,
            timeout=60.0,
            max_bytes=max_response_bytes,
            allowed_private_hosts=allowed_private_hosts,
            allowed_redirect_hosts=allowed_redirect_hosts,
            transport=transport,
        )

    return _fetch


def _cursor_value(value: Any) -> str | None:
    """Render a cursor candidate; ``0`` is a valid cursor, other falsy values are not."""
    if value or (isinstance(value, int) and not isinstance(value, bool)):
        return str(value)
    return None
