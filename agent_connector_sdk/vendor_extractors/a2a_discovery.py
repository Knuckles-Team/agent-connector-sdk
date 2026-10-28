"""Governed discovery of an A2A agent card.

The extractor-facing discovery path deliberately reuses the SDK HTTP client.
It keeps the small cache in process so a later pull can use ``ETag`` without
making a second transport or egress implementation for A2A cards.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from agent_connector_sdk.http.bodies import read_bounded
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.egress import EgressPolicyError, PinnedEgressViolation
from agent_connector_sdk.http.errors import HttpProblemError, ResponseTooLargeError
from agent_connector_sdk.http.options import HttpClientOptions

__all__ = [
    "AGENT_CARD_PATH",
    "DEFAULT_AGENT_CARD_CACHE_ENTRIES",
    "DEFAULT_DISCOVERY_TIMEOUT_SECONDS",
    "DEFAULT_MAX_AGENT_CARD_BYTES",
    "AgentCardRefused",
    "DiscoveredAgentCard",
    "discover_agent_card",
]

AGENT_CARD_PATH = "/.well-known/agent-card.json"
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_AGENT_CARD_BYTES = 256 * 1024
DEFAULT_AGENT_CARD_CACHE_ENTRIES = 64

_RefusalReason = Literal["not_found", "not_json", "oversize", "egress_blocked"]
_CACHE: OrderedDict[str, DiscoveredAgentCard] = OrderedDict()
_CACHE_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class DiscoveredAgentCard:
    """One bounded, source-pinned observation of a remote agent card."""

    base_url: str
    card: dict[str, Any]
    fetched_at: str
    etag: str | None
    skills: tuple[str, ...]

    @property
    def source_url(self) -> str:
        """The exact well-known resource that produced ``card``."""
        return f"{self.base_url.rstrip('/')}{AGENT_CARD_PATH}"


@dataclass(frozen=True, slots=True)
class AgentCardRefused:
    """A card that was not admitted to the extractor change set."""

    reason: _RefusalReason


def _cache_key(base_url: str) -> str:
    return base_url.rstrip("/")


def _client_options(base_url: str, *, allow_loopback: bool) -> HttpClientOptions:
    """Build the named discovery limits on the governed client boundary."""
    return HttpClientOptions(
        base_url=base_url,
        timeout=DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
        pin_egress=True,
        allow_loopback=allow_loopback,
    )


def _skill_ids(card: dict[str, Any]) -> tuple[str, ...]:
    values = card.get("skills", ())
    if isinstance(values, dict):
        values = tuple(values.values())
    if not isinstance(values, (list, tuple)):
        return ()
    identifiers: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("id") or value.get("name")
        if isinstance(value, str) and value.strip():
            identifiers.append(value.strip())
    return tuple(identifiers)


def _cached(
    base_url: str, previous: DiscoveredAgentCard | None
) -> DiscoveredAgentCard | None:
    key = _cache_key(base_url)
    if previous is not None and _cache_key(previous.base_url) == key:
        return previous
    with _CACHE_LOCK:
        return _touch_cached(key)


def _touch_cached(key: str) -> DiscoveredAgentCard | None:
    result = _CACHE.get(key)
    if result is not None:
        _CACHE.move_to_end(key)
    return result


def _evict_oldest() -> None:
    while len(_CACHE) > DEFAULT_AGENT_CARD_CACHE_ENTRIES:
        _CACHE.popitem(last=False)


def _remember(card: DiscoveredAgentCard) -> None:
    with _CACHE_LOCK:
        key = _cache_key(card.base_url)
        _CACHE[key] = card
        _CACHE.move_to_end(key)
        _evict_oldest()


def _refused(reason: _RefusalReason) -> AgentCardRefused:
    return AgentCardRefused(reason=reason)


def discover_agent_card(
    base_url: str,
    *,
    previous: DiscoveredAgentCard | None = None,
    allow_loopback: bool = False,
) -> DiscoveredAgentCard | AgentCardRefused:
    """Fetch one A2A card through the governed HTTP client.

    A successful result is cached by base URL. Subsequent pulls send its ETag;
    a ``304`` returns the cached immutable observation without parsing a body.
    Refusals carry only a fixed reason, so upstream bodies and credentials do
    not cross the extractor boundary.
    """
    key = _cache_key(base_url)
    cached = _cached(base_url, previous)
    headers = {"Accept-Encoding": "identity"}
    if cached and cached.etag:
        headers["If-None-Match"] = cached.etag

    try:
        options = _client_options(base_url, allow_loopback=allow_loopback)
        with (
            create_http_client(options) as client,
            client.stream("GET", AGENT_CARD_PATH, headers=headers) as response,
        ):
            if response.status_code == 304:
                if cached is None:
                    return _refused("not_found")
                _remember(cached)
                return cached
            if response.status_code == 404:
                return _refused("not_found")
            if response.status_code != 200:
                return _refused("not_found")
            if (
                response.headers.get("content-encoding", "identity").lower()
                != "identity"
            ):
                return _refused("not_json")
            body = read_bounded(response, DEFAULT_MAX_AGENT_CARD_BYTES)
            try:
                value = json.loads(body)
            except (TypeError, ValueError):
                return _refused("not_json")
            if not isinstance(value, dict):
                return _refused("not_json")
            discovered = DiscoveredAgentCard(
                base_url=key,
                card=value,
                fetched_at=datetime.now(UTC).isoformat(),
                etag=response.headers.get("etag") or None,
                skills=_skill_ids(value),
            )
    except ResponseTooLargeError:
        return _refused("oversize")
    except (EgressPolicyError, PinnedEgressViolation, ValueError):
        return _refused("egress_blocked")
    except HttpProblemError:
        return _refused("not_found")

    _remember(discovered)
    return discovered
