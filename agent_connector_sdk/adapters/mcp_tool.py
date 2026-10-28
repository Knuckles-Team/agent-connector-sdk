"""Declarative MCP-tool source adapter for generated EG ingestion values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
)

from agent_connector_sdk.adapters.mcp_tool_extract import (
    _mapped_records,
    _mapped_relationships,
    _page_checkpoint,
)
from agent_connector_sdk.adapters.mcp_tool_fanout import (
    FAN_KEY,
    check_parents,
    extract_fanned,
    parent_values,
)
from agent_connector_sdk.adapters.mcp_tool_lifecycle import (
    _ingestion_mode,
    _source_withdrawals,
    authoritative_live_ids,
    raw_relationships,
)
from agent_connector_sdk.adapters.mcp_tool_paging import page_params, tool_arguments
from agent_connector_sdk.adapters.mcp_tool_records import raw_records
from agent_connector_sdk.adapters.tool_contract import (
    describe_preset_adapter,
    discover_tool_backed_stream,
)
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.ingest.for_each import MAX_FAN_OUT
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping, SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["McpToolSourceAdapter"]


def _require_identity(connector: str, mapping_reference: str) -> None:
    if not all((connector, mapping_reference)):
        raise ValueError("connector and mapping_reference are required")


class McpToolSourceAdapter:
    """Extract one declared stream through an MCP tool."""

    kind = "mcp_tool"

    def __init__(
        self,
        preset: ToolPreset,
        *,
        connector: str,
        mapping_reference: str,
        tool_schema_sha256: str = "",
        schema_mappings: Mapping[str, SchemaMapping] | None = None,
        resources: Sequence[ResourceSpec] = (),
        parents: Mapping[str, ToolPreset] | None = None,
        max_fan_out: int = MAX_FAN_OUT,
    ) -> None:
        _require_identity(connector, mapping_reference)
        self._parents = dict(parents or {})
        self._max_fan_out = max_fan_out
        if preset.for_each is not None:
            check_parents(preset, self._parents)
        self._preset = preset
        self._connector = connector
        self._pinned = tool_schema_sha256
        self._mapping_reference = mapping_reference
        self._schema_mappings = dict(schema_mappings or {})
        self._resources = {resource.name: resource for resource in resources}
        self._verified_sha256 = ""
        self._fan_values: list[Any] | None = None

    @classmethod
    def from_sync_spec(
        cls,
        spec: SyncSpec,
        *,
        connector: str,
        mapping_reference: str,
        schema_mappings: Mapping[str, SchemaMapping] | None = None,
        resources: Sequence[ResourceSpec] = (),
        parents: Mapping[str, SyncSpec] | None = None,
        max_fan_out: int = MAX_FAN_OUT,
    ) -> McpToolSourceAdapter:
        """Build an adapter from a sync declaration.

        The tool fingerprint is the live compatibility fingerprint read at
        discovery (SDK-CONNECTOR-CONTROL-R075.3).
        """
        return cls(
            ToolPreset.from_mapping(spec.preset, dict(spec.raw)),
            connector=connector,
            mapping_reference=mapping_reference,
            schema_mappings=schema_mappings,
            resources=resources,
            parents={
                name: ToolPreset.from_mapping(name, dict(parent.raw))
                for name, parent in (parents or {}).items()
            },
            max_fan_out=max_fan_out,
        )

    @property
    def preset(self) -> ToolPreset:
        """The preset this adapter extracts."""
        return self._preset

    def derive(self, preset: ToolPreset) -> McpToolSourceAdapter:
        """An adapter for ``preset`` that shares this adapter's verified tool."""
        derived = McpToolSourceAdapter(
            preset,
            connector=self._connector,
            mapping_reference=self._mapping_reference,
            tool_schema_sha256=self._pinned,
            schema_mappings=self._schema_mappings,
            resources=tuple(self._resources.values()),
        )
        derived._verified_sha256 = self._verified_sha256
        return derived

    @property
    def stream(self) -> str:
        return self._preset.name

    def describe(self) -> CapabilityDescriptor:
        return describe_preset_adapter(
            self.kind, self._preset, incremental=bool(self._preset.updated_field)
        )

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the live tool against its pinned compatibility fingerprint."""
        preset = self._preset
        self._verified_sha256, descriptor = await discover_tool_backed_stream(
            session,
            preset,
            pinned_schema_sha256=self._pinned,
            identifier_fields=(preset.id_field,),
        )
        return descriptor

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Extract the provider page after EG's accepted checkpoint."""
        current = checkpoint or SourceCheckpoint(stream=self.stream, position={})
        if not self._verified_sha256 or current.stream != self.stream:
            raise SourceContractError(
                "extraction needs a verified tool and this stream's checkpoint"
            )
        if self._preset.for_each is not None:
            if not isinstance(current.position, Mapping) or (
                FAN_KEY not in current.position
            ):
                self._fan_values = None  # a new sweep re-reads the parents
            values = await self._fan_out_values(session)
            return await extract_fanned(self, session, current, values)
        since: Any = (
            current.position if self._preset.checkpoint_path else current.watermark
        )
        params = page_params(self._preset, current.position, since)
        result = await session.call_tool(
            self._preset.tool, tool_arguments(self._preset, params)
        )
        observed = validate_preset_tool_contract(
            await session.list_tools(),
            tool_name=self._preset.tool,
            presets=(self._preset,),
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
        if (
            mode is not SourceIngestionMode.DELTA
            and self._preset.pagination == "none"
            and not self._preset.checkpoint_path
        ):
            # Unpaged snapshots have no provider cursor. Each completed sweep
            # needs a fresh durable position for EG's checkpoint compare-and-set.
            candidate = candidate.model_copy(
                update={"position": {"sdk_snapshot": uuid4().hex}}
            )
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
            schema_contract=observed.schema_contract.model_copy(
                update={"identifier_fields": (self._preset.id_field,)}
            ),
        )

    async def _fan_out_values(self, session: McpSession) -> list[Any]:
        if self._fan_values is None:
            self._fan_values = await parent_values(
                session, self._preset, self._parents, limit=self._max_fan_out
            )
        return self._fan_values

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
