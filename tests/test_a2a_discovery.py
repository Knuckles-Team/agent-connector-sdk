"""SDK-CONNECTOR-CONTROL-R047 agent-card discovery contract tests."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.vendor_extractors.a2a import extract
from agent_connector_sdk.vendor_extractors.a2a_discovery import (
    AGENT_CARD_PATH,
    DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    DEFAULT_MAX_AGENT_CARD_BYTES,
    AgentCardRefused,
    DiscoveredAgentCard,
    discover_agent_card,
)


def _body(*, name: str = "Research Agent") -> bytes:
    return json.dumps(
        {"name": name, "skills": [{"id": "search"}, {"name": "plan"}]}
    ).encode()


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R047.1")
def test_discovered_card_is_frozen_and_typed() -> None:
    card = DiscoveredAgentCard(
        base_url="https://agent.example",
        card={"name": "Agent"},
        fetched_at="2026-01-01T00:00:00+00:00",
        etag='"v1"',
        skills=("search",),
    )
    assert isinstance(card.card, dict)
    assert isinstance(card.skills, tuple)
    assert DEFAULT_DISCOVERY_TIMEOUT_SECONDS == 10.0
    with pytest.raises(FrozenInstanceError):
        card.base_url = "https://other.example"  # type: ignore[misc]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R047.2")
def test_fetch_uses_well_known_path_and_etag() -> None:
    with ScriptedHttpServer(
        ScriptedResponse(
            body=_body(),
            headers={"Content-Type": "application/json", "ETag": '"v1"'},
        ),
        ScriptedResponse(status=304, headers={"ETag": '"v1"'}),
    ) as server:
        first = discover_agent_card(server.base_url, allow_loopback=True)
        second = discover_agent_card(server.base_url, allow_loopback=True)

    assert isinstance(first, DiscoveredAgentCard)
    assert second == first
    assert [request.path for request in server.requests] == [
        AGENT_CARD_PATH,
        AGENT_CARD_PATH,
    ]
    assert server.requests[1].headers["if-none-match"] == '"v1"'


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R047.4")
def test_refusals_write_nothing() -> None:
    cases = (
        (ScriptedResponse(status=404), "not_found"),
        (ScriptedResponse(body=b"not-json"), "not_json"),
        (
            ScriptedResponse(body=b"x" * (DEFAULT_MAX_AGENT_CARD_BYTES + 1)),
            "oversize",
        ),
    )
    for response, reason in cases:
        with ScriptedHttpServer(response) as server:
            result = discover_agent_card(server.base_url, allow_loopback=True)
        assert isinstance(result, AgentCardRefused)
        assert result.reason == reason

    for base_url in (
        "ftp://agent.example",
        "http://10.0.0.1",
        "https://user:secret@example.com",
    ):
        result = discover_agent_card(base_url)
        assert isinstance(result, AgentCardRefused)
        assert result.reason == "egress_blocked"
        assert "secret" not in repr(result)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R047.5")
def test_entity_carries_fetch_provenance() -> None:
    with ScriptedHttpServer(
        ScriptedResponse(
            body=_body(),
            headers={"Content-Type": "application/json", "ETag": '"v2"'},
        )
    ) as server:
        result = extract({"cards": [server.base_url], "allow_loopback": True})

    entity = next(
        entity for entity in result.entities if entity.node_type == "A2AAgentCard"
    )
    assert entity.properties["source_url"] == f"{server.base_url}{AGENT_CARD_PATH}"
    assert entity.properties["etag"] == '"v2"'
    assert entity.properties["fetched_at"]


def test_loopback_requires_explicit_opt_in() -> None:
    with ScriptedHttpServer(ScriptedResponse(body=_body())) as server:
        assert discover_agent_card(server.base_url) == AgentCardRefused(
            "egress_blocked"
        )
        assert extract({"cards": [server.base_url]}).entities == ()
        assert not server.requests


def test_compressed_card_is_refused_before_decoding() -> None:
    with ScriptedHttpServer(
        ScriptedResponse(body=b"not gzip", headers={"Content-Encoding": "gzip"})
    ) as server:
        result = discover_agent_card(server.base_url, allow_loopback=True)
    assert result == AgentCardRefused("not_json")
    assert server.requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R047.7")
def test_discovery_cache_is_bounded_and_refreshes_hits(monkeypatch) -> None:
    from collections import OrderedDict

    from agent_connector_sdk.vendor_extractors import a2a_discovery as discovery

    assert discovery.DEFAULT_AGENT_CARD_CACHE_ENTRIES == 64
    monkeypatch.setattr(discovery, "DEFAULT_AGENT_CARD_CACHE_ENTRIES", 2)
    monkeypatch.setattr(discovery, "_CACHE", OrderedDict())

    def card(name: str) -> DiscoveredAgentCard:
        return DiscoveredAgentCard(
            base_url=f"https://{name}.example",
            card={"name": name},
            fetched_at="2026-01-01T00:00:00+00:00",
            etag='"v1"',
            skills=(),
        )

    first, second, third = card("first"), card("second"), card("third")
    discovery._remember(first)
    discovery._remember(second)
    assert discovery._cached(first.base_url, None) == first
    discovery._remember(third)
    assert discovery._cached(second.base_url, None) is None
    assert discovery._cached(first.base_url, None) == first
    assert discovery._cached(third.base_url, None) == third
    assert len(discovery._CACHE) == 2


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R047.8")
def test_cached_card_is_isolated_from_returned_mutations() -> None:
    with ScriptedHttpServer(
        ScriptedResponse(body=_body(), headers={"ETag": '"v1"'}),
        ScriptedResponse(status=304),
        ScriptedResponse(status=304),
    ) as server:
        first = discover_agent_card(server.base_url, allow_loopback=True)
        assert isinstance(first, DiscoveredAgentCard)
        first.card["skills"][0]["id"] = "changed"
        second = discover_agent_card(server.base_url, allow_loopback=True)
        assert isinstance(second, DiscoveredAgentCard)
        assert second.card["skills"][0]["id"] == "search"
        second.card["skills"].clear()
        third = discover_agent_card(server.base_url, allow_loopback=True)
        assert isinstance(third, DiscoveredAgentCard)
        assert third.card["skills"][0]["id"] == "search"
        assert all(
            request.headers.get("if-none-match") == '"v1"'
            for request in server.requests[1:]
        )
