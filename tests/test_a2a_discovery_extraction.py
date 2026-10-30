"""SCION-CONNECTOR-CONTROL-R047.4 refusal exclusion at the extractor boundary."""

from __future__ import annotations

from scion_sdk.ingest import ChangeSet
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from scion_sdk.vendor_extractors import a2a_helpers
from scion_sdk.vendor_extractors.a2a import extract
from scion_sdk.vendor_extractors.a2a_discovery import AgentCardRefused


def test_refused_discovery_is_excluded_from_extractor_changeset(monkeypatch) -> None:
    outcomes = []
    discover = a2a_helpers.discover_agent_card

    def record_outcome(base_url: str, **kwargs):
        outcome = discover(base_url, **kwargs)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(a2a_helpers, "discover_agent_card", record_outcome)

    with ScriptedHttpServer(ScriptedResponse(status=404)) as server:
        result = extract({"cards": [server.base_url], "allow_loopback": True})

    assert len(outcomes) == 1
    assert outcomes[0] == AgentCardRefused(reason="not_found")
    assert [request.path for request in server.requests] == [
        "/.well-known/agent-card.json"
    ]
    assert result == ChangeSet()
    assert result.entities == ()
    assert result.relationships == ()
