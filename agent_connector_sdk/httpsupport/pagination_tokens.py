"""Bounded continuation-token history for one pagination walk."""

from __future__ import annotations

import hashlib
from typing import Any


class _TokenHistory:
    """Keep fixed-size fingerprints, never provider token text."""

    def __init__(self, initial: Any) -> None:
        self._seen: set[tuple[type[Any], bytes]] = set()
        if initial is not None:
            self.observe(initial)

    def observe(self, token: Any) -> bool:
        key = (type(token), hashlib.sha256(str(token).encode("utf-8")).digest())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def _advance_token(
    walk: Any, token: Any, parameter: str
) -> tuple[str, dict[str, Any]] | None:
    """Stop a repeated continuation without presenting it as resumable."""
    if not walk._tokens.observe(token):
        walk.loop_detected = True
        walk.next_cursor = None
        return None
    walk.next_cursor = str(token)
    params = dict(walk.base_params)
    params[parameter] = token
    return walk.endpoint, params


def _advance_cursor(walk: Any, cursor: Any) -> tuple[str, dict[str, Any]] | None:
    if not cursor:
        walk.next_cursor = None
        return None
    return _advance_token(walk, cursor, walk.cursor_param)


def _advance_since(walk: Any, items: list[Any]) -> tuple[str, dict[str, Any]] | None:
    last = items[-1] if items else None
    last_id = last.get(walk.id_field) if isinstance(last, dict) else None
    if last_id is None:
        walk.next_cursor = None
        return None
    return _advance_token(walk, last_id, walk.since_param)


def _advance_numbered(walk: Any, items: list[Any]) -> tuple[str, dict[str, Any]] | None:
    if not items or (walk.page_size is not None and len(items) < walk.page_size):
        return None
    if walk.mode == "page":
        walk._page += 1
    else:
        walk._offset += len(items)
    return walk.start()
