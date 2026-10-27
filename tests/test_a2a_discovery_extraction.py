"""SDK-CONNECTOR-CONTROL-R047.4 refusal exclusion at the extractor boundary."""

from __future__ import annotations

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.vendor_extractors import a2a_helpers
from agent_connector_sdk.vendor_extractors.a2a import extract
from agent_connector_sdk.vendor_extractors.a2a_discovery import AgentCardRefused


def test_refused_discovery_is_excluded_from_extractor_changeset(monkeypatch) -> None:
    outcomes = []
    discover = a2a_helpers.discover_agent_card

    def record_outcome(base_url: str):
        outcome = discover(base_url)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(a2a_helpers, "discover_agent_card", record_outcome)

    with ScriptedHttpServer(ScriptedResponse(status=404)) as server:
        result = extract({"cards": [server.base_url]})

    assert len(outcomes) == 1
    assert outcomes[0] == AgentCardRefused(reason="not_found")
    assert [request.path for request in server.requests] == [
        "/.well-known/agent-card.json"
    ]
    assert result == ChangeSet()
    assert result.entities == ()
    assert result.relationships == ()
