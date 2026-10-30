"""Governed discovery of an A2A agent card.

The extractor-facing discovery path deliberately reuses the SDK HTTP client.
It keeps the small cache in process so a later pull can use ``ETag`` without
making a second transport or egress implementation for A2A cards.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from functools import partial

from anyio.from_thread import start_blocking_portal

from scion_sdk.http.egress import EgressPolicyError, PinnedEgressViolation
from scion_sdk.http.errors import HttpProblemError, ResponseTooLargeError
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.vendor_extractors._a2a_card_fetch import _fetch_card
from scion_sdk.vendor_extractors._a2a_card_types import (
    AGENT_CARD_PATH,
    DEFAULT_AGENT_CARD_CACHE_ENTRIES,
    DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    DEFAULT_MAX_AGENT_CARD_BYTES,
    AgentCardRefused,
    DiscoveredAgentCard,
    _refused,
)

__all__ = [
    "AGENT_CARD_PATH",
    "DEFAULT_AGENT_CARD_CACHE_ENTRIES",
    "DEFAULT_DISCOVERY_TIMEOUT_SECONDS",
    "DEFAULT_MAX_AGENT_CARD_BYTES",
    "AgentCardRefused",
    "DiscoveredAgentCard",
    "discover_agent_card",
]

_CACHE: OrderedDict[str, DiscoveredAgentCard] = OrderedDict()
_CACHE_LOCK = threading.RLock()


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
        return replace(result, card=json.loads(json.dumps(result.card)))
    return None


def _evict_oldest() -> None:
    while len(_CACHE) > DEFAULT_AGENT_CARD_CACHE_ENTRIES:
        _CACHE.popitem(last=False)


def _remember(card: DiscoveredAgentCard) -> None:
    with _CACHE_LOCK:
        key = _cache_key(card.base_url)
        _CACHE[key] = replace(card, card=json.loads(json.dumps(card.card)))
        _CACHE.move_to_end(key)
        _evict_oldest()


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

    deadline = time.monotonic() + DEFAULT_DISCOVERY_TIMEOUT_SECONDS
    try:
        with start_blocking_portal() as portal:
            discovered = portal.call(
                partial(
                    _fetch_card,
                    _client_options(base_url, allow_loopback=allow_loopback),
                    key,
                    cached=cached,
                    headers=headers,
                    deadline=deadline,
                )
            )
    except TimeoutError:
        return _refused("not_found")
    except ResponseTooLargeError:
        return _refused("oversize")
    except (EgressPolicyError, PinnedEgressViolation, ValueError):
        return _refused("egress_blocked")
    except HttpProblemError:
        return _refused("not_found")

    if isinstance(discovered, DiscoveredAgentCard):
        _remember(discovered)
    return discovered
