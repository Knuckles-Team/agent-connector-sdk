"""Declarative MCP-tool source adapter for generated EG ingestion values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
)

from agent_connector_sdk.adapters.mcp_tool_extract import (
    _mapped_records,
    _mapped_relationships,
    _page_checkpoint,
)
from agent_connector_sdk.adapters.mcp_tool_lifecycle import (
    _ingestion_mode,
    _source_withdrawals,
    authoritative_live_ids,
    raw_relationships,
)
from agent_connector_sdk.adapters.mcp_tool_paging import page_params, tool_arguments
from agent_connector_sdk.adapters.mcp_tool_records import raw_records
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping, SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import ToolSchemaContractError
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["McpToolSourceAdapter"]


def _require_identity(
    connector: str, tool_schema_sha256: str, mapping_reference: str
) -> None:
    if not all((connector, tool_schema_sha256, mapping_reference)):
        raise ValueError(
            "connector, mapping_reference and a pinned tool_schema_sha256 are required"
        )


class McpToolSourceAdapter:
    """Extract one manifest-declared stream through an MCP tool."""

    kind = "mcp_tool"

    def __init__(
        self,
        preset: ToolPreset,
        *,
        connector: str,
        tool_schema_sha256: str,
        mapping_reference: str,
        schema_mappings: Mapping[str, SchemaMapping] | None = None,
        resources: Sequence[ResourceSpec] = (),
    ) -> None:
        _require_identity(connector, tool_schema_sha256, mapping_reference)
        self._preset = preset
        self._connector = connector
        self._pinned = tool_schema_sha256
        self._mapping_reference = mapping_reference
        self._schema_mappings = dict(schema_mappings or {})
        self._resources = {resource.name: resource for resource in resources}
        self._verified_sha256 = ""

    @classmethod
    def from_sync_spec(
        cls,
        spec: SyncSpec,
        *,
        connector: str,
        mapping_reference: str,
        schema_mappings: Mapping[str, SchemaMapping] | None = None,
        resources: Sequence[ResourceSpec] = (),
    ) -> McpToolSourceAdapter:
        """Build an adapter from a manifest sync declaration."""
        return cls(
            ToolPreset.from_mapping(spec.preset, dict(spec.raw)),
            connector=connector,
            tool_schema_sha256=spec.tool_schema_sha256 or "",
            mapping_reference=mapping_reference,
            schema_mappings=schema_mappings,
            resources=resources,
        )

    @property
    def stream(self) -> str:
        return self._preset.name

    def describe(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            kind=self.kind,
            pagination=(self._preset.pagination,),
            incremental=bool(self._preset.updated_field),
            certified_for_ingestion=True,
        )

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the live tool against its pinned compatibility fingerprint."""
        preset = self._preset
        try:
            contract = validate_preset_tool_contract(
                await session.list_tools(),
                tool_name=preset.tool,
                presets=(preset,),
                expected_schema_sha256=self._pinned,
            )
        except ToolSchemaContractError as exc:
            raise SourceContractError(str(exc)) from exc
        self._verified_sha256 = contract.compatibility_sha256
        return StreamDescriptor(
            stream=self.stream,
            tool=preset.tool,
            schema_sha256=contract.compatibility_sha256,
        )

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Extract the provider page after EG's accepted checkpoint."""
        current = checkpoint or SourceCheckpoint(stream=self.stream, position={})
        if not self._verified_sha256 or current.stream != self.stream:
            raise SourceContractError(
                "extraction needs a verified tool and this stream's checkpoint"
            )
        since: Any = (
            current.position if self._preset.checkpoint_path else current.watermark
        )
        params = page_params(self._preset, current.position, since)
        result = await session.call_tool(
            self._preset.tool, tool_arguments(self._preset, params)
        )
        raw = raw_records(self._preset, result)
        records, references = _mapped_records(
            raw,
            connector=self._connector,
            preset=self._preset,
            configured_mapping=self._mapping_reference,
            mappings=self._schema_mappings,
            schema_sha256=self._verified_sha256,
            since=current.watermark,
        )
        candidate, exhausted = _page_checkpoint(
            self._preset, current, records, result=result, raw=raw
        )
        live_ids = authoritative_live_ids(self._preset, result)
        mode = _ingestion_mode(
            self._preset,
            result=result,
            live_ids=live_ids,
            checkpoint=checkpoint,
        )
        withdrawals = _source_withdrawals(self._preset, result)
        if mode is not SourceIngestionMode.DELTA and withdrawals:
            raise SourceContractError("only delta ingestion accepts withdrawals")
        relationships = _mapped_relationships(
            raw_relationships(self._preset, result),
            connector=self._connector,
            preset=self._preset,
            mappings=self._schema_mappings,
            resources=self._resources,
            mappings_by_id=references,
            schema_sha256=self._verified_sha256,
        )
        return RecordPage(
            records=records,
            relationships=relationships,
            mode=mode,
            strict_schema=self._preset.strict_schema,
            checkpoint=candidate,
            authoritative_live_ids=live_ids,
            withdrawals=withdrawals,
            exhausted=exhausted,
        )

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Sweep every page without a watermark and diff source identities."""
        seen: set[str] = set()
        checkpoint: SourceCheckpoint | None = None
        for _ in range(self._preset.max_pages):
            page = await self.extract(session, checkpoint)
            seen.update(record.record_id for record in page.records)
            if page.exhausted:
                return ReconciliationReport(
                    stream=self.stream,
                    missing_from_source=tuple(sorted(known_ids - seen)),
                    unknown_to_sink=tuple(sorted(seen - known_ids)),
                )
            checkpoint = page.checkpoint.model_copy(update={"watermark": None})
        raise SourceContractError("reconciliation sweep exceeded max_pages")
