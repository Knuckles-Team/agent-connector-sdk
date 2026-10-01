"""The event feed engine: one ``SourceAdapter`` for every feed kind.

One engine serves RUM, security-audit and CI/CD events alike
(SDK-OBSERVABILITY-FEEDS-R001): the wire shape (server, tool, pagination) is a
:class:`ToolPreset` like any other ``mcp_tool`` source, and the event envelope
(identity, time basis, privacy label, digest) is validated the same way
regardless of which feed kind is read. Per-record validation and identity
handling live in :mod:`agent_connector_sdk.adapters.event_feed_records`; the
three concrete feed-kind bindings live in
:mod:`agent_connector_sdk.adapters.event_feed_bindings`. Each feed kind
narrows only its required payload fields; parsing one vendor's specific event
shape belongs to that connector's own repository, not here.

Event feeds are append-only: a feed does not declare an authoritative live
set the way a document source can, so this adapter does not reconcile, and it
does not support a provider-declared ``checkpoint_path``, relationships, or
withdrawals. Deletions and retention expiry surface as explicit outcomes
instead (a tombstone stream, or :class:`FeedRetentionExpiredError`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
)

from agent_connector_sdk.adapters.event_envelope import FeedKind
from agent_connector_sdk.adapters.event_feed_records import (
    _check_feed_status,
    _event_source_record,
)
from agent_connector_sdk.adapters.event_identity import EventIdentityTracker
from agent_connector_sdk.adapters.mcp_tool_paging import (
    checkpoint_after_page,
    next_position,
    page_params,
    tool_arguments,
)
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
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["EventFeedSourceAdapter"]

#: Preset fields this adapter does not implement; a configured value is refused
#: at construction rather than silently ignored.
_UNSUPPORTED_PRESET_FIELDS = (
    "checkpoint_path",
    "relationships_path",
    "reconcile_path",
    "authoritative_path",
    "withdrawals_path",
)


def _require_identity(
    connector: str, tool_schema_sha256: str, mapping_reference: str
) -> None:
    if not all((connector, tool_schema_sha256, mapping_reference)):
        raise ValueError(
            "connector, mapping_reference and a pinned tool_schema_sha256 are required"
        )


def _reject_unsupported_preset_fields(preset: ToolPreset) -> None:
    configured = [name for name in _UNSUPPORTED_PRESET_FIELDS if getattr(preset, name)]
    if configured:
        raise ValueError(
            f"preset {preset.name!r}: event feeds do not support {', '.join(configured)}"
        )


class EventFeedSourceAdapter:
    """Extract one operational event feed stream, validating its envelope.

    The provider contract, pagination and checkpoint are declared the same
    way as :class:`agent_connector_sdk.adapters.mcp_tool.McpToolSourceAdapter`;
    only event-specific validation, identity and status handling differ.
    """

    def __init__(
        self,
        preset: ToolPreset,
        *,
        feed_kind: FeedKind,
        connector: str,
        tool_schema_sha256: str,
        mapping_reference: str,
    ) -> None:
        _require_identity(connector, tool_schema_sha256, mapping_reference)
        _reject_unsupported_preset_fields(preset)
        self.kind = f"event_feed:{feed_kind.value}"
        self._preset = preset
        self._feed_kind = feed_kind
        self._connector = connector
        self._pinned = tool_schema_sha256
        self._mapping_reference = mapping_reference
        self._verified_sha256 = ""
        self._tracker = EventIdentityTracker()

    @property
    def stream(self) -> str:
        return self._preset.name

    def describe(self) -> CapabilityDescriptor:
        return describe_preset_adapter(
            self.kind, self._preset, incremental=bool(self._preset.updated_since_param)
        )

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the live tool against its pinned compatibility fingerprint."""
        self._verified_sha256, descriptor = await discover_tool_backed_stream(
            session, self._preset, pinned_schema_sha256=self._pinned
        )
        return descriptor

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Extract the provider page after EG's accepted checkpoint.

        Raises:
            FeedBackpressureError: the provider is rate limited or down.
            FeedRetentionExpiredError: the checkpoint fell outside retention.
        """
        preset = self._preset
        current = checkpoint or SourceCheckpoint(stream=self.stream, position={})
        if not self._verified_sha256 or current.stream != self.stream:
            raise SourceContractError(
                "extraction needs a verified tool and this stream's checkpoint"
            )
        params = page_params(preset, current.position, current.watermark)
        result = await session.call_tool(preset.tool, tool_arguments(preset, params))
        _check_feed_status(result)
        # Unpinned: observe the live schema for this page without enforcing the
        # adapter's compatibility pin again; drift is classified downstream by
        # the runner's schema-drift quarantine, not raised here.
        _, observed = await discover_tool_backed_stream(
            session, preset, pinned_schema_sha256=""
        )
        raw = raw_records(preset, result)
        records = self._mapped_events(raw)
        position = current.position if isinstance(current.position, Mapping) else {}
        next_page = next_position(preset, position, result=result, raw=raw)
        return RecordPage(
            records=records,
            mode=SourceIngestionMode.DELTA,
            strict_schema=False,
            checkpoint=checkpoint_after_page(current, records, next_page),
            exhausted=next_page is None,
            schema_contract=observed.schema_contract,
        )

    def _mapped_events(self, raw: list[dict[str, Any]]) -> tuple[SourceRecord, ...]:
        records = (
            _event_source_record(
                self._preset,
                item,
                feed_kind=self._feed_kind,
                connector=self._connector,
                schema_sha256=self._verified_sha256,
                mapping_reference=self._mapping_reference,
                tracker=self._tracker,
            )
            for item in raw
        )
        return tuple(record for record in records if record is not None)

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Event feeds are append-only; use tombstone and expiry outcomes instead."""
        raise SourceContractError(
            "event feeds do not reconcile a live set; see tombstone and "
            "retention-expiry outcomes"
        )
