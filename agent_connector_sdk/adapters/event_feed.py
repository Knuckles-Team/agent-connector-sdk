"""Declarative source adapter for RUM, security-audit and CI/CD event feeds.

One engine serves every feed kind (SDK-OBSERVABILITY-FEEDS-R001): the wire
shape (server, tool, pagination) is a :class:`ToolPreset` like any other
``mcp_tool`` source, and the event envelope (identity, time basis, privacy
label, digest) is validated the same way regardless of which feed kind is
read. Each feed kind narrows only its required payload fields; parsing one
vendor's specific event shape belongs to that connector's own repository, not
here.

Event feeds are append-only: a feed does not declare an authoritative live
set the way a document source can, so this adapter does not reconcile, and it
does not support a provider-declared ``checkpoint_path``, relationships, or
withdrawals. Deletions and retention expiry surface as explicit outcomes
instead (a tombstone stream, or :class:`FeedRetentionExpiredError`).
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import ValidationError

from agent_connector_sdk.adapters.event_envelope import (
    EventEnvelope,
    FeedKind,
    compute_payload_digest,
)
from agent_connector_sdk.adapters.event_errors import (
    FeedBackpressureError,
    FeedRetentionExpiredError,
)
from agent_connector_sdk.adapters.event_identity import (
    EventIdentityOutcome,
    EventIdentityTracker,
)
from agent_connector_sdk.adapters.mcp_tool_paging import (
    checkpoint_after_page,
    dig_path,
    next_position,
    page_params,
    tool_arguments,
)
from agent_connector_sdk.adapters.mcp_tool_records import raw_records
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import ToolSchemaContractError
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.ports.session import McpSession

__all__ = [
    "EventFeedSourceAdapter",
    "ci_cd_source_adapter",
    "rum_source_adapter",
    "security_audit_source_adapter",
]

#: Payload fields SDK-OBSERVABILITY-FEEDS-R001 requires each feed kind to carry.
_REQUIRED_PAYLOAD_FIELDS: dict[FeedKind, tuple[str, ...]] = {
    FeedKind.RUM: ("signal", "page", "session_id"),
    FeedKind.SECURITY_AUDIT: (
        "principal",
        "action",
        "target",
        "outcome",
        "audit_chain_reference",
        "scope",
    ),
    FeedKind.CI_CD: ("repository_revision", "job_id", "run_id", "attempt", "status"),
}

#: Field names no event payload may carry, regardless of feed kind.
_DENYLISTED_PAYLOAD_FIELDS = frozenset(
    {"password", "token", "secret", "authorization", "ssn", "credit_card", "api_key"}
)

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


def _validate_feed_payload(feed_kind: FeedKind, payload: Mapping[str, Any]) -> None:
    missing = [
        field for field in _REQUIRED_PAYLOAD_FIELDS[feed_kind] if field not in payload
    ]
    if missing:
        raise MalformedSourceDataError(
            f"{feed_kind.value} event payload is missing {', '.join(missing)}"
        )
    forbidden = sorted(_DENYLISTED_PAYLOAD_FIELDS & payload.keys())
    if forbidden:
        raise MalformedSourceDataError(
            f"event payload carries forbidden fields: {', '.join(forbidden)}"
        )


def _check_scope_matches_tenant(
    feed_kind: FeedKind, payload: Mapping[str, Any], tenant_id: str
) -> None:
    if feed_kind is FeedKind.SECURITY_AUDIT and payload.get("scope") != tenant_id:
        raise SourceContractError("audit event scope does not match its tenant")


def _check_feed_status(result: Any) -> None:
    """Refuse a page the provider could not actually serve.

    429/outage and an expired retention window surface as typed errors, never
    as a fabricated empty or complete page.
    """
    status = dig_path(result, "status") if isinstance(result, Mapping) else None
    if status in (None, "ok"):
        return
    if status == "rate_limited":
        raise FeedBackpressureError(
            "event feed is rate limited",
            retry_after_seconds=dig_path(result, "retry_after_seconds"),
        )
    if status == "retention_expired":
        raise FeedRetentionExpiredError(
            "checkpoint position fell outside the provider's retention window"
        )
    raise SourceContractError(f"event feed reported an unknown status {status!r}")


def _envelope_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """``raw`` without the fields this adapter computes or injects itself."""
    return {
        k: v
        for k, v in raw.items()
        if k not in ("payload", "payload_digest", "feed_kind")
    }


def _event_source_record(
    preset: ToolPreset,
    raw: Any,
    *,
    feed_kind: FeedKind,
    connector: str,
    schema_sha256: str,
    mapping_reference: str,
    tracker: EventIdentityTracker,
) -> SourceRecord | None:
    """Validate one raw event into its envelope, or ``None`` for a duplicate.

    Raises:
        MalformedSourceDataError: the event, its payload, or its envelope does
            not satisfy the standard shape.
        EventIdentityConflictError: a repeated event id changed its payload.
        SourceContractError: the event names a different stream than the one
            this adapter extracts.
    """
    if not isinstance(raw, Mapping):
        raise MalformedSourceDataError("event record is not an object")
    payload = raw.get("payload")
    if not isinstance(payload, Mapping):
        raise MalformedSourceDataError("event record has no object payload")
    _validate_feed_payload(feed_kind, payload)
    try:
        envelope = EventEnvelope(
            **_envelope_fields(raw),
            feed_kind=feed_kind,
            payload=dict(payload),
            payload_digest=compute_payload_digest(payload),
        )
    except ValidationError as exc:
        raise MalformedSourceDataError(f"malformed event envelope: {exc}") from exc
    if envelope.stream != preset.name:
        raise SourceContractError("event names a stream other than this adapter's own")
    _check_scope_matches_tenant(feed_kind, payload, envelope.tenant_id)
    record_id = envelope.identity
    if (
        tracker.classify(record_id, envelope.payload_digest)
        is EventIdentityOutcome.DUPLICATE
    ):
        return None
    provenance = SourceRecordProvenance(
        connector=connector,
        adapter_kind=f"event_feed:{feed_kind.value}",
        server=preset.server,
        tool=preset.tool,
        tool_schema_sha256=schema_sha256,
        source_uri=f"event-feed://{preset.server}/{preset.tool}/{feed_kind.value}/{record_id}",
    )
    return SourceRecord(
        stream=preset.name,
        record_id=record_id,
        mapping_reference=mapping_reference,
        payload=envelope.model_dump(mode="json"),
        updated_at=envelope.event_time.isoformat(),
        provenance=provenance,
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
        return CapabilityDescriptor(
            kind=self.kind,
            pagination=(self._preset.pagination,),
            incremental=bool(self._preset.updated_since_param),
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
            schema_contract=contract.schema_contract,
            evolution_policy=preset.evolution_policy,
        )

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
        observed = validate_preset_tool_contract(
            await session.list_tools(), tool_name=preset.tool, presets=(preset,)
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


#: One provider implementation per feed kind (SDK-OBSERVABILITY-FEEDS-R001):
#: the engine above is shared, and only the feed kind is fixed.
rum_source_adapter = functools.partial(EventFeedSourceAdapter, feed_kind=FeedKind.RUM)
security_audit_source_adapter = functools.partial(
    EventFeedSourceAdapter, feed_kind=FeedKind.SECURITY_AUDIT
)
ci_cd_source_adapter = functools.partial(
    EventFeedSourceAdapter, feed_kind=FeedKind.CI_CD
)
