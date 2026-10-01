"""Per-record validation, privacy and identity handling for event feeds.

Turns one raw provider event into a validated :class:`EventEnvelope`-backed
``SourceRecord`` (or ``None`` for an idempotent duplicate), and refuses a page
the provider could not actually serve. Kept separate from the adapter engine
in :mod:`agent_connector_sdk.adapters.event_feed` so each file stays under the
repository's per-file size caps.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from epistemic_graph.generated.source_ingestion import (
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
from agent_connector_sdk.adapters.mcp_tool_paging import dig_path
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)

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
