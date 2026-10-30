"""Card-parsing helpers for the A2A agent-card extractor."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from scion_sdk.vendor_extractors._records import (
    _get,
)
from scion_sdk.vendor_extractors.a2a_discovery import (
    DiscoveredAgentCard,
    discover_agent_card,
)

_DISCOVERY_KEY = "__sdk_discovered_agent_card__"


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


def _raw_items(config: Any) -> list[Any]:
    if isinstance(config, str):
        return [config]
    if isinstance(config, list | tuple):
        return list(config)
    raw = _get(config, "cards", []) or []
    return [raw] if isinstance(raw, str | dict) else raw


def _discovered_card(base_url: str, allow_loopback: bool) -> list[dict[str, Any]]:
    discovered = discover_agent_card(base_url, allow_loopback=allow_loopback)
    if not isinstance(discovered, DiscoveredAgentCard):
        return []
    card = dict(discovered.card)
    card[_DISCOVERY_KEY] = discovered
    return [card]


def _expand_item(item: Any, allow_loopback: bool) -> list[dict[str, Any]]:
    if isinstance(item, dict):
        base_url = item.get("base_url")
        if isinstance(base_url, str):
            return _discovered_card(base_url, allow_loopback)
        return [item]
    if not isinstance(item, str):
        return []
    if "://" in item:
        return _discovered_card(item, allow_loopback)
    return _load_json(item) if os.path.exists(item) else []


def _collect_cards(config: Any) -> list[dict[str, Any]]:
    """Resolve ``config`` into a flat list of AgentCard dicts.

    Accepts a dict carrying ``cards`` (list of card dicts and/or path
    strings), a single path string, or a list of paths/card dicts.
    """
    allow_loopback = _get(config, "allow_loopback", False) is True
    cards: list[dict[str, Any]] = []
    for item in _raw_items(config):
        cards.extend(_expand_item(item, allow_loopback))
    return cards
