"""The ``mcp_tool`` source adapter: extract records through a connector's MCP tool.

The reference :class:`~agent_connector_sdk.ports.source_adapter.SourceAdapter`,
ported from ``agent_utilities.protocols.source_connectors.connectors.mcp_tool``.
What changed on the way out:

* It emits raw :class:`~agent_connector_sdk.contracts.SourceRecord` values.
  Documents, field mappings and access control are the ingestion authority's
  job, so AU's document and ACL projection, per-record detail fetches and SQL
  table sweeps are not part of extraction.
* It is always governed: construction requires the pinned
  ``tool_schema_sha256``, :meth:`McpToolSourceAdapter.discover` must verify the
  live tool before any extraction, and records that do not match the preset
  raise instead of being skipped.
* It opens no connections; a :class:`~agent_connector_sdk.ports.transport.Transport`
  supplies the session, so the same adapter runs over HTTP, stdio or in process.
"""

from __future__ import annotations

from agent_connector_sdk.adapters.mcp_tool_paging import (
    cursor_after_page,
    next_position,
    page_params,
    tool_arguments,
)
from agent_connector_sdk.adapters.mcp_tool_records import raw_records, source_record
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
    SyncCursor,
)
from agent_connector_sdk.manifest.live_contract import validate_live_tool_contract
from agent_connector_sdk.manifest.model import SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import ToolSchemaContractError
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["McpToolSourceAdapter"]


class McpToolSourceAdapter:
    """Extract one preset's records through its MCP tool.

    Args:
        preset: The validated preset naming tool, arguments and pagination.
        connector: The connector package that owns the preset.
        tool_schema_sha256: The pinned compatibility fingerprint of the tool.
    """

    kind = "mcp_tool"

    def __init__(
        self, preset: ToolPreset, *, connector: str, tool_schema_sha256: str
    ) -> None:
        if not connector or not tool_schema_sha256:
            raise ValueError("connector and a pinned tool_schema_sha256 are required")
        self._preset = preset
        self._connector = connector
        self._pinned = tool_schema_sha256
        self._verified_sha256 = ""

    @classmethod
    def from_sync_spec(cls, spec: SyncSpec, *, connector: str) -> McpToolSourceAdapter:
        """Build an adapter from a manifest ``sync`` entry (its ``raw`` preset)."""
        return cls(
            ToolPreset.from_mapping(spec.preset, dict(spec.raw)),
            connector=connector,
            tool_schema_sha256=spec.tool_schema_sha256 or "",
        )

    @property
    def stream(self) -> str:
        """The stream this adapter extracts (the preset name)."""
        return self._preset.name

    def describe(self) -> CapabilityDescriptor:
        """Declared capabilities; performs no I/O."""
        return CapabilityDescriptor(
            kind=self.kind,
            pagination=(self._preset.pagination,),
            incremental=bool(self._preset.updated_field),
            certified_for_ingestion=True,
        )

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the live tool against the pinned fingerprint and argument types.

        Raises:
            SourceContractError: the tool is missing or its schema drifted.
        """
        preset = self._preset
        required = {preset.action_param: "string"} if preset.action else {}
        if preset.params_style == "json":
            required[preset.params_arg] = "string"
        try:
            contract = validate_live_tool_contract(
                await session.list_tools(),
                tool_name=preset.tool,
                expected_schema_sha256=self._pinned,
                required_argument_types=required,
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
        self, session: McpSession, cursor: SyncCursor | None
    ) -> RecordPage:
        """Extract the page after ``cursor``.

        Raises:
            SourceContractError: ``discover`` has not verified the tool, or the
                cursor belongs to another stream.
            MalformedSourceDataError: the response does not match the preset.
        """
        current = cursor or SyncCursor(stream=self.stream)
        if not self._verified_sha256 or current.stream != self.stream:
            raise SourceContractError(
                "extraction needs a verified tool and this stream's cursor"
            )
        params = page_params(self._preset, current.position, current.watermark)
        result = await session.call_tool(
            self._preset.tool, tool_arguments(self._preset, params)
        )
        raw = raw_records(self._preset, result)
        since = current.watermark
        records = tuple(
            record
            for record in (
                source_record(
                    self._preset,
                    item,
                    connector=self._connector,
                    schema_sha256=self._verified_sha256,
                )
                for item in raw
            )
            if not (
                since and record.updated_at is not None and record.updated_at <= since
            )
        )
        position = next_position(self._preset, current.position, result=result, raw=raw)
        return RecordPage(
            records=records,
            cursor=cursor_after_page(current, records, position),
            exhausted=position is None,
        )

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Sweep every page without a watermark and diff ids against ``known_ids``.

        Raises:
            SourceContractError: the sweep did not finish within ``max_pages``; an
                incomplete sweep cannot prove a record is missing.
        """
        seen: set[str] = set()
        cursor: SyncCursor | None = None
        for _ in range(self._preset.max_pages):
            page = await self.extract(session, cursor)
            seen.update(record.record_id for record in page.records)
            if page.exhausted:
                return ReconciliationReport(
                    stream=self.stream,
                    missing_from_source=tuple(sorted(known_ids - seen)),
                    unknown_to_sink=tuple(sorted(seen - known_ids)),
                )
            cursor = page.cursor.model_copy(update={"watermark": None})
        raise SourceContractError("reconciliation sweep exceeded max_pages")
