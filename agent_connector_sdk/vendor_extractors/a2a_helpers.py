"""Card-parsing helpers for the A2A agent-card extractor."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from agent_connector_sdk.vendor_extractors._records import (
    _get,
)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug[:80] or "agent"


def _scalar(value: Any) -> str | None:
    """Normalise a possibly-nested value to a scalar string (or None)."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("organization")
            or value.get("id")
            or value.get("value")
        )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tags(value: Any) -> list[str]:
    """Coerce a skill's tags field into a clean list of strings."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple | set):
        return []
    out: list[str] = []
    for item in value:
        text = _scalar(item)
        if text:
            out.append(text)
    return out


def _dict_items(items: list[Any]) -> list[dict[str, Any]]:
    return [card for card in items if isinstance(card, dict)]


def _cards_from_data(data: Any) -> list[dict[str, Any]]:
    """Normalise parsed JSON into a list of card dicts."""
    if isinstance(data, dict):
        inner = data.get("cards")
        if isinstance(inner, list):
            return _dict_items(inner)
        return [data]
    if isinstance(data, list):
        return _dict_items(data)
    return []


def _load_json(path: str) -> list[dict[str, Any]]:
    """Read+json.load a card file, returning a list of card dicts (tolerant)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    return _cards_from_data(data)


def _collect_cards(config: Any) -> list[dict[str, Any]]:
    """Resolve ``config`` into a flat list of AgentCard dicts.

    Accepts a dict carrying ``cards`` (list of card dicts and/or path
    strings), a single path string, or a list of paths/card dicts.
    """
    raw: Any
    if isinstance(config, str):
        raw = [config]
    elif isinstance(config, list | tuple):
        raw = list(config)
    else:
        raw = _get(config, "cards", []) or []
        if isinstance(raw, str | dict):
            raw = [raw]

    cards: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            cards.append(item)
        elif isinstance(item, str) and os.path.exists(item):
            cards.extend(_load_json(item))
    return cards
