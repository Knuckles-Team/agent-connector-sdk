"""Remote GraphOS ConnectorPack authority is live and caller-bound."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import Any

import pytest
from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    McpCatalogSnapshotBinding,
)

from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.catalog_authority import (
    CatalogAuthorityError,
    RemotePackImportAuthorityResolver,
)

CALLER = "principal:sha256:" + hashlib.sha256(b"service:runner").hexdigest()


def _response() -> dict[str, Any]:
    return {
        "connector": "sample-agent",
        "catalog_binding": McpCatalogSnapshotBinding(
            configuration_revision=7,
            catalog_generation=11,
            snapshot_digest="a" * 64,
            child_connection_generation=3,
            authorization_scope_digest="b" * 64,
        ).model_dump(mode="json"),
        "mutation_context": AgentLibraryMutationContext(
            request_id=1,
            principal="service:runner",
            caller_principal=CALLER,
            attempt_nonce="07" * 32,
            tenant_id="tenant-a",
            actor_scope="scope-a",
            purpose_id="purpose-a",
            policy_revision="policy-1",
            policy_digest="sha256:" + "c" * 64,
            policy_decision_id="decision-1",
            idempotency_key="caller-value",
            expected_revision=1,
            created_at_ms=1_700_000_000_000,
        ).model_dump(mode="json"),
    }


class _Session:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def call_tool(self, name: str, arguments: dict[str, str]) -> Any:
        self.calls.append((name, arguments))
        return self.response


class _Transport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.sessions: list[_Session] = []

    @asynccontextmanager
    async def session(self, _endpoint: TransportEndpoint):
        session = _Session(self.response)
        self.sessions.append(session)
        yield session


def _resolver(
    response: dict[str, Any],
    *,
    principal: str = "service:runner",
) -> tuple[RemotePackImportAuthorityResolver, _Transport]:
    transport = _Transport(response)
    endpoint = TransportEndpoint(
        url="https://graphos.example.invalid/mcp",
        auth=object(),  # type: ignore[arg-type]
    )
    resolver = RemotePackImportAuthorityResolver(
        endpoint,
        tenant="tenant-a",
        principal=principal,
        transport=transport,  # type: ignore[arg-type]
    )
    return resolver, transport


@pytest.mark.asyncio
async def test_remote_authority_is_fresh_and_request_only_names_connector() -> None:
    resolver, transport = _resolver(_response())
    catalog, context = await resolver("sample-agent")
    assert catalog.catalog_generation == 11
    assert (context.tenant_id, context.caller_principal) == (
        "tenant-a",
        CALLER,
    )
    await resolver("sample-agent")
    assert len(transport.sessions) == 2
    assert [s.calls for s in transport.sessions] == [
        [("connector_pack_authority", {"connector": "sample-agent"})]
    ] * 2


@pytest.mark.asyncio
async def test_already_opaque_principal_is_not_hashed_twice() -> None:
    resolver, _ = _resolver(_response(), principal=CALLER)
    _, context = await resolver("sample-agent")
    assert context.caller_principal == CALLER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"connector": "foreign-agent"},
        {
            "mutation_context": {
                **_response()["mutation_context"],
                "tenant_id": "tenant-b",
            }
        },
        {
            "mutation_context": {
                **_response()["mutation_context"],
                "caller_principal": "service:other",
            }
        },
        {"catalog_binding": {**_response()["catalog_binding"], "unknown": True}},
    ],
)
async def test_remote_authority_refuses_foreign_or_malformed_result(
    change: dict[str, Any],
) -> None:
    resolver, _ = _resolver({**_response(), **change})
    with pytest.raises(CatalogAuthorityError):
        await resolver("sample-agent")


def test_remote_authority_requires_authenticated_url_and_identity() -> None:
    with pytest.raises(CatalogAuthorityError, match="secure MCP URL"):
        RemotePackImportAuthorityResolver(
            TransportEndpoint(
                url="http://graphos.example.invalid/mcp",
                auth=object(),  # type: ignore[arg-type]
            ),
            tenant="tenant-a",
            principal="service:runner",
        )
    with pytest.raises(CatalogAuthorityError):
        RemotePackImportAuthorityResolver(
            TransportEndpoint(url="https://graphos.example.invalid/mcp"),
            tenant="tenant-a",
            principal="service:runner",
        )
    with pytest.raises(CatalogAuthorityError):
        RemotePackImportAuthorityResolver(
            TransportEndpoint(url="https://graphos.example.invalid/mcp", auth=object()),  # type: ignore[arg-type]
            tenant="tenant-b ",
            principal="service:runner",
        )
