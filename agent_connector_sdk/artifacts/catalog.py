"""Tenant-bound read of SDK connector items from EG's published pack catalog.

The SDK never infers an operation from a live probe or a local checkout. EG's
current, pack-owned manifest is the only source of the connector description.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import yaml
from epistemic_graph.connector_pack import ConnectorPackClient
from epistemic_graph.generated.agent_component import (
    AgentComponentContentRequest,
    AgentComponentEntry,
    AgentComponentKind,
    AgentComponentSearchRequest,
    AgentLibraryLifecycle,
)
from epistemic_graph.generated.storage import (
    send_agent_component_content,
    send_agent_component_search,
)
from pydantic import ValidationError

from agent_connector_sdk.manifest.model import ConnectorManifest

__all__ = ["VerifiedPackCatalogReader"]

_MANIFEST_URI = "manifest://connector"
_PAGE_SIZE = 128
_MAX_PAGES = 16
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


class VerifiedPackCatalogReader:
    """Read published connector controls through one authenticated EG client.

    ``client`` must already be bound to the verified request tenant and caller.
    The reader supplies the exact tenant on every generated request and checks
    the returned rows. It exposes only whole-connector sync because the served
    GraphOS ingest control does not offer per-preset execution.
    """

    def __init__(self, client: Any, *, tenant_id: str) -> None:
        if client is None or not tenant_id.strip():
            raise ValueError("verified EG client and tenant_id are required")
        self._client = client
        self._tenant_id = tenant_id
        self._packs = ConnectorPackClient(client)

    async def sdk_entries(self) -> tuple[Mapping[str, Any], ...]:
        """Return bounded, currently published operation pointers or fail closed."""
        manifests = await self._manifest_entries()
        rows: list[Mapping[str, Any]] = []
        connectors: set[str] = set()
        for entry in manifests:
            attributes = entry.attributes or {}
            connector = attributes.get("pack.connector")
            if not connector or connector in connectors:
                raise ValueError("pack manifest has absent or duplicate connector")
            connectors.add(connector)
            before = await self._packs.status(
                tenant_id=self._tenant_id, connector=connector
            )
            self._require_head(before, connector)
            content = await send_agent_component_content(
                self._client,
                AgentComponentContentRequest(
                    tenant_id=self._tenant_id,
                    component_id=entry.component_id,
                    entry_revision=entry.entry_revision,
                ),
                self._tenant_id,
            )
            if (
                content.component_id != entry.component_id
                or content.entry_revision != entry.entry_revision
                or content.definition_digest != entry.definition_digest
                or content.content_digest != entry.content_digest
                or content.content_digest
                != "sha256:" + hashlib.sha256(content.body).hexdigest()
                or len(content.body) > _MAX_MANIFEST_BYTES
            ):
                raise ValueError("pack manifest content differs from its EG pin")
            manifest = self._parse_manifest(content.body, connector)
            after = await self._packs.status(
                tenant_id=self._tenant_id, connector=connector
            )
            self._require_head(after, connector)
            if before.head != after.head:
                raise ValueError("pack head changed during catalog read")
            head = after.head
            if head is None:
                raise ValueError("pack status lacks a verified current head")
            provenance = {
                "tenant_id": self._tenant_id,
                "pack_digest": head.pack_digest,
                "manifest_definition_digest": entry.definition_digest,
                "manifest_content_digest": entry.content_digest,
                "actor_scope": entry.actor_scope,
                "policy_digest": entry.policy_digest,
                "purpose_id": entry.purpose_id,
            }
            if manifest.sync:
                rows.append(
                    {
                        **provenance,
                        "pack": connector,
                        "name": "sync",
                        "op": "ingest.sources.sync",
                        "description": f"Sync {connector} connector sources",
                        "params": {"connector": connector},
                        "required_scopes": ("source:ingest",),
                    }
                )
            rows.append(
                {
                    **provenance,
                    "pack": connector,
                    "name": "status",
                    "op": "ingest.packs.status",
                    "description": f"Read {connector} pack status",
                    "params": {"connector": connector},
                    "required_scopes": ("agent:pack-control",),
                }
            )
        return tuple(sorted(rows, key=lambda row: (row["pack"], row["name"])))

    async def _manifest_entries(self) -> tuple[AgentComponentEntry, ...]:
        found: list[AgentComponentEntry] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            page = await send_agent_component_search(
                self._client,
                AgentComponentSearchRequest(
                    tenant_id=self._tenant_id,
                    kinds=[AgentComponentKind.MCP_RESOURCE],
                    limit=_PAGE_SIZE,
                    cursor=cursor,
                ),
                self._tenant_id,
            )
            for entry in page.entries:
                if entry.tenant_id != self._tenant_id:
                    raise ValueError("pack catalog search crossed the verified tenant")
                attributes = entry.attributes or {}
                if attributes.get("mcp.uri") != _MANIFEST_URI:
                    continue
                if (
                    entry.source_revision != "connector-pack"
                    or entry.lifecycle is not AgentLibraryLifecycle.PUBLISHED
                    or attributes.get("connector.manifest") != "true"
                    or not attributes.get("pack.entry_digest")
                ):
                    raise ValueError("pack manifest lacks published EG provenance")
                found.append(entry)
            cursor = page.next_cursor
            if cursor is None:
                return tuple(found)
            if cursor in seen_cursors:
                raise ValueError("pack catalog cursor repeated")
            seen_cursors.add(cursor)
        raise ValueError("pack catalog exceeded page bound")

    def _require_head(self, status: Any, connector: str) -> None:
        if (
            status.tenant_id != self._tenant_id
            or status.connector != connector
            or status.head is None
            or not status.head.pack_digest
        ):
            raise ValueError("pack status lacks a verified current head")

    @staticmethod
    def _parse_manifest(body: bytes, connector: str) -> ConnectorManifest:
        try:
            document = yaml.safe_load(body)
            manifest = ConnectorManifest.model_validate(document)
        except (UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
            raise ValueError("EG pack manifest is malformed") from exc
        if manifest.connector != connector:
            raise ValueError("EG pack manifest names a different connector")
        return manifest
