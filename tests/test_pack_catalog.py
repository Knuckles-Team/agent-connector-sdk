"""Verified SDK connector-item read through EG's generated pack authority."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from agent_connector_sdk.artifacts import catalog

_BODY = b"""connector: demo
sync:
- preset: demo
  server: demo-mcp
  tool: read
provenance:
  integrity:
    hash: '0000000000000000000000000000000000000000000000000000000000000000'
"""


def _entry(**changes: Any) -> SimpleNamespace:
    row = {
        "tenant_id": "tenant-a",
        "attributes": {
            "mcp.uri": "manifest://connector",
            "pack.connector": "demo",
            "pack.entry_digest": "a" * 64,
            "connector.manifest": "true",
        },
        "source_revision": "connector-pack",
        "lifecycle": catalog.AgentLibraryLifecycle.PUBLISHED,
        "component_id": "mcp:demo/mcp_resource/manifest",
        "entry_revision": 7,
        "definition_digest": "sha256:" + "b" * 64,
        "content_digest": "sha256:" + hashlib.sha256(_BODY).hexdigest(),
        "actor_scope": "service:connector-sync",
        "policy_digest": "sha256:" + "c" * 64,
        "purpose_id": "pack-publication",
    }
    row.update(changes)
    return SimpleNamespace(**row)


def _content(entry: SimpleNamespace, body: bytes = _BODY) -> SimpleNamespace:
    return SimpleNamespace(
        component_id=entry.component_id,
        entry_revision=entry.entry_revision,
        definition_digest=entry.definition_digest,
        content_digest=entry.content_digest,
        body=body,
    )


def _status(head: object | None = None) -> SimpleNamespace:
    if head is None:
        head = SimpleNamespace(pack_digest="a" * 64)
    return SimpleNamespace(tenant_id="tenant-a", connector="demo", head=head)


def _setup(monkeypatch: pytest.MonkeyPatch, entry: SimpleNamespace) -> list[str]:
    calls: list[str] = []

    async def search(_client: object, request: Any, graph: str) -> SimpleNamespace:
        assert request.tenant_id == graph == "tenant-a"
        calls.append("search")
        return SimpleNamespace(entries=[entry], next_cursor=None)

    async def content(_client: object, request: Any, graph: str) -> SimpleNamespace:
        assert request.tenant_id == graph == "tenant-a"
        assert request.entry_revision == 7
        calls.append("content")
        return _content(entry)

    class Packs:
        def __init__(self, _client: object) -> None:
            pass

        async def status(self, *, tenant_id: str, connector: str) -> SimpleNamespace:
            assert tenant_id == "tenant-a" and connector == "demo"
            calls.append("status")
            return _status()

    monkeypatch.setattr(catalog, "send_agent_component_search", search)
    monkeypatch.setattr(catalog, "send_agent_component_content", content)
    monkeypatch.setattr(catalog, "ConnectorPackClient", Packs)
    return calls


@pytest.mark.asyncio
async def test_verified_manifest_exposes_only_served_whole_connector_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _setup(monkeypatch, _entry())
    rows = await catalog.VerifiedPackCatalogReader(
        object(), tenant_id="tenant-a"
    ).sdk_entries()
    assert [(row["pack"], row["name"], row["op"]) for row in rows] == [
        ("demo", "status", "ingest.packs.status"),
        ("demo", "sync", "ingest.sources.sync"),
    ]
    assert rows[1]["params"] == {"connector": "demo"}
    assert rows[1]["required_scopes"] == ("source:ingest",)
    assert rows[1]["tenant_id"] == "tenant-a"
    assert rows[1]["pack_digest"] == "a" * 64
    assert rows[1]["manifest_content_digest"] == (
        "sha256:" + hashlib.sha256(_BODY).hexdigest()
    )
    assert rows[1]["actor_scope"] == "service:connector-sync"
    assert calls == ["search", "status", "content", "status"]


@pytest.mark.asyncio
async def test_cross_tenant_or_unproven_manifest_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for entry in (
        _entry(tenant_id="tenant-b"),
        _entry(source_revision="local-file"),
        _entry(lifecycle=catalog.AgentLibraryLifecycle.RETIRED),
    ):
        _setup(monkeypatch, entry)
        with pytest.raises(ValueError):
            await catalog.VerifiedPackCatalogReader(
                object(), tenant_id="tenant-a"
            ).sdk_entries()


@pytest.mark.asyncio
async def test_missing_pack_head_and_mismatched_body_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry()
    _setup(monkeypatch, entry)

    class NoHead:
        def __init__(self, _client: object) -> None:
            pass

        async def status(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(tenant_id="tenant-a", connector="demo", head=None)

    monkeypatch.setattr(catalog, "ConnectorPackClient", NoHead)
    with pytest.raises(ValueError, match="head"):
        await catalog.VerifiedPackCatalogReader(
            object(), tenant_id="tenant-a"
        ).sdk_entries()

    _setup(monkeypatch, entry)

    async def changed_content(
        _client: object, _request: Any, _graph: str
    ) -> SimpleNamespace:
        return _content(entry, b"tampered")

    monkeypatch.setattr(catalog, "send_agent_component_content", changed_content)
    with pytest.raises(ValueError, match="pin"):
        await catalog.VerifiedPackCatalogReader(
            object(), tenant_id="tenant-a"
        ).sdk_entries()
