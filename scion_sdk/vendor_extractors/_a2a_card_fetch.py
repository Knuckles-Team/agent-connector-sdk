"""Bounded fetch and parse of one A2A agent card."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from math import isfinite
from typing import Any

import anyio

from scion_sdk.http.bodies import aread_bounded
from scion_sdk.http.client import create_async_http_client
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.vendor_extractors._a2a_card_types import (
    AGENT_CARD_PATH,
    DEFAULT_MAX_AGENT_CARD_BYTES,
    AgentCardRefused,
    DiscoveredAgentCard,
    _refused,
)


def _finite_json_float(text: str) -> float:
    value = float(text)
    if not isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _reject_json_constant(text: str) -> None:
    raise ValueError("non-finite JSON number")


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


def _status_outcome(
    status: int, cached: DiscoveredAgentCard | None
) -> DiscoveredAgentCard | AgentCardRefused | None:
    """The terminal outcome for a non-200 status, or ``None`` to read the body."""
    if status == 200:
        return None
    if status == 304 and cached is not None:
        return cached
    return _refused("not_found")


def _parse_card(body: bytes | str) -> dict[str, Any] | None:
    try:
        value = json.loads(
            body,
            parse_float=_finite_json_float,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def _fetch_card(
    options: HttpClientOptions,
    key: str,
    *,
    cached: DiscoveredAgentCard | None,
    headers: dict[str, str],
    deadline: float,
) -> DiscoveredAgentCard | AgentCardRefused:
    with anyio.fail_after(max(0.0, deadline - time.monotonic())):
        async with (
            create_async_http_client(options) as client,
            client.stream("GET", AGENT_CARD_PATH, headers=headers) as response,
        ):
            outcome = _status_outcome(response.status_code, cached)
            if outcome is not None:
                return outcome
            if (
                response.headers.get("content-encoding", "identity").lower()
                != "identity"
            ):
                return _refused("not_json")
            body = await aread_bounded(response, DEFAULT_MAX_AGENT_CARD_BYTES)
            value = _parse_card(body)
            if value is None:
                return _refused("not_json")
            etag = response.headers.get("etag") or None
    return DiscoveredAgentCard(
        base_url=key,
        card=value,
        fetched_at=datetime.now(UTC).isoformat(),
        etag=etag,
        skills=_skill_ids(value),
    )
