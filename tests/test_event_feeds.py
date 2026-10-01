"""SDK-OBSERVABILITY-FEEDS-R001: RUM, security-audit and CI/CD event feeds.

OF-01..OF-05 run offline against a fake in-memory MCP session (no network, no
production telemetry). OF-06 is opt-in acceptance against a contributor-owned
graph and is recorded NOT RUN here, per the spec's completion section.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.adapters.event_envelope import (
    EventEnvelope,
    FeedKind,
    VisibilityLabel,
    compute_payload_digest,
)
from agent_connector_sdk.adapters.event_errors import (
    EventIdentityConflictError,
    FeedBackpressureError,
    FeedRetentionExpiredError,
)
from agent_connector_sdk.adapters.event_feed import (
    EventFeedSourceAdapter,
    ci_cd_source_adapter,
    rum_source_adapter,
    security_audit_source_adapter,
)
from agent_connector_sdk.adapters.event_identity import (
    EventIdentityOutcome,
    EventIdentityTracker,
)
from agent_connector_sdk.manifest.live_contract import validate_live_tool_contract
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.runner.errors import SchemaDriftQuarantined
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.testing.sinks import InMemorySink

CONNECTOR = "observability-demo"
_T0 = datetime(2026, 9, 30, tzinfo=UTC)


def _tool_descriptor(
    tool_name: str, *, extra_required: str | None = None
) -> dict[str, Any]:
    output_properties: dict[str, Any] = {
        "status": {"type": "string"},
        "events": {"type": "array"},
        "cursor": {"type": ["string", "null"]},
    }
    required = ["status", "events", "cursor"]
    if extra_required is not None:
        output_properties[extra_required] = {"type": "string"}
        required.append(extra_required)
    return {
        "name": tool_name,
        "inputSchema": {
            "type": "object",
            "properties": {"params_json": {"type": "string"}},
        },
        "outputSchema": {
            "type": "object",
            "required": required,
            "properties": output_properties,
        },
    }


def _compatibility_sha256(descriptor: dict[str, Any]) -> str:
    return validate_live_tool_contract(
        {"tools": [descriptor]}, tool_name=descriptor["name"]
    ).compatibility_sha256


class FakeEventSession:
    """A minimal ``McpSession`` serving canned event feed pages in sequence."""

    def __init__(
        self, *, descriptor: dict[str, Any], pages: Sequence[Mapping[str, Any]]
    ) -> None:
        self._descriptor = descriptor
        self._pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    async def server_identity(self) -> Any:
        raise NotImplementedError

    async def list_tools(self) -> Sequence[Any]:
        return [self._descriptor]

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        assert name == self._descriptor["name"]
        self.calls.append(dict(arguments))
        assert self._pages, "fake session ran out of pages"
        return self._pages.pop(0)

    async def list_prompts(self) -> Sequence[Any]:
        raise NotImplementedError

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> Any:
        raise NotImplementedError

    async def list_resources(self) -> Sequence[Any]:
        raise NotImplementedError

    async def read_resource(self, uri: str) -> str:
        raise NotImplementedError


def _preset(name: str, tool: str) -> ToolPreset:
    return ToolPreset(
        name=name,
        server="observability-mcp",
        tool=tool,
        records_path="events",
        pagination="cursor",
        cursor_param="cursor",
        cursor_path="cursor",
        updated_since_param="since",
    )


def _adapter(
    factory: Any, preset: ToolPreset, *, descriptor: dict[str, Any] | None = None
) -> EventFeedSourceAdapter:
    descriptor = descriptor or _tool_descriptor(preset.tool)
    return factory(
        preset,
        connector=CONNECTOR,
        tool_schema_sha256=_compatibility_sha256(descriptor),
        mapping_reference=f"manifest:{CONNECTOR}#schema_mappings/Event",
    )


def _event(
    *,
    provider_event_id: str,
    source: str,
    stream: str,
    actor_ref: str,
    target_ref: str,
    payload: dict[str, Any],
    offset_seconds: float = 0,
    visibility_label: str = VisibilityLabel.INTERNAL.value,
    tenant_id: str = "tenant-a",
) -> dict[str, Any]:
    at = (_T0 + timedelta(seconds=offset_seconds)).isoformat()
    return {
        "tenant_id": tenant_id,
        "source": source,
        "stream": stream,
        "event_kind": f"{stream}.event",
        "schema_version": "1",
        "provider_event_id": provider_event_id,
        "event_time": at,
        "source_observed_time": at,
        "ingest_time": at,
        "actor_ref": actor_ref,
        "target_ref": target_ref,
        "visibility_label": visibility_label,
        "payload": payload,
    }


def _rum_event(
    provider_event_id: str, *, payload_extra: dict[str, Any] | None = None, **kw: Any
) -> dict[str, Any]:
    payload = {"signal": "page_view", "page": "/checkout", "session_id": "session-1"}
    payload.update(payload_extra or {})
    return _event(
        provider_event_id=provider_event_id,
        source="sentry-rum",
        stream="rum-stream",
        actor_ref="session-1",
        target_ref="/checkout",
        payload=payload,
        **kw,
    )


def _audit_event(
    provider_event_id: str,
    *,
    scope: str = "tenant-a",
    payload_extra: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    payload = {
        "principal": "user:alice",
        "action": "update",
        "target": "resource:42",
        "outcome": "success",
        "audit_chain_reference": "chain:1",
        "scope": scope,
    }
    payload.update(payload_extra or {})
    return _event(
        provider_event_id=provider_event_id,
        source="okta-audit",
        stream="audit-stream",
        actor_ref="user:alice",
        target_ref="resource:42",
        payload=payload,
        **kw,
    )


def _ci_event(
    provider_event_id: str,
    *,
    attempt: int = 1,
    status: str = "running",
    payload_extra: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    payload = {
        "repository_revision": "abc123",
        "job_id": "job-1",
        "run_id": "run-1",
        "attempt": attempt,
        "status": status,
    }
    payload.update(payload_extra or {})
    return _event(
        provider_event_id=provider_event_id,
        source="github-actions",
        stream="ci-stream",
        actor_ref="ci-system",
        target_ref="job-1",
        payload=payload,
        **kw,
    )


def _page(
    *events: dict[str, Any], cursor: str | None = None, status: str = "ok", **extra: Any
) -> dict[str, Any]:
    return {"status": status, "events": list(events), "cursor": cursor, **extra}


async def _single_page_sweep(
    adapter: EventFeedSourceAdapter, session: FakeEventSession
) -> Any:
    await adapter.discover(session)
    return await adapter.extract(session, None)


# ---------------------------------------------------------------------------
# OF-01: RUM action/error/session event.
# ---------------------------------------------------------------------------


async def test_rum_event_carries_identity_time_privacy_and_digest() -> None:
    preset = _preset("rum-stream", "rum_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool), pages=[_page(_rum_event("rum-1"))]
    )
    page = await _single_page_sweep(_adapter(rum_source_adapter, preset), session)
    assert len(page.records) == 1
    record = page.records[0]
    assert record.record_id == "rum-1"
    assert record.updated_at == _T0.isoformat()
    assert record.payload["visibility_label"] == VisibilityLabel.INTERNAL.value
    assert record.payload["payload_digest"] == compute_payload_digest(
        {"signal": "page_view", "page": "/checkout", "session_id": "session-1"}
    )
    assert len(record.payload["payload_digest"]) == 64


async def test_rum_event_refuses_raw_credential_fields() -> None:
    preset = _preset("rum-stream", "rum_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(_rum_event("rum-2", payload_extra={"token": "s3cr3t"}))],
    )
    with pytest.raises(MalformedSourceDataError, match="forbidden"):
        await _single_page_sweep(_adapter(rum_source_adapter, preset), session)


# ---------------------------------------------------------------------------
# OF-02: security-audit principal/action/target/outcome event.
# ---------------------------------------------------------------------------


async def test_audit_event_retains_outcome_and_chain_reference() -> None:
    preset = _preset("audit-stream", "audit_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool), pages=[_page(_audit_event("audit-1"))]
    )
    page = await _single_page_sweep(
        _adapter(security_audit_source_adapter, preset), session
    )
    payload = page.records[0].payload["payload"]
    assert (
        payload["outcome"] == "success"
        and payload["audit_chain_reference"] == "chain:1"
    )


async def test_audit_event_scope_mismatch_refuses() -> None:
    preset = _preset("audit-stream", "audit_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(_audit_event("audit-2", scope="tenant-b"))],
    )
    with pytest.raises(SourceContractError, match="scope"):
        await _single_page_sweep(
            _adapter(security_audit_source_adapter, preset), session
        )


# ---------------------------------------------------------------------------
# OF-03: CI job with retries and a deployment artifact.
# ---------------------------------------------------------------------------


async def test_ci_retry_is_not_conflated_with_first_attempt() -> None:
    preset = _preset("ci-stream", "ci_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[
            _page(
                _ci_event("ci-1", attempt=1, status="failed", offset_seconds=0),
                _ci_event(
                    "ci-2",
                    attempt=2,
                    status="succeeded",
                    offset_seconds=30,
                    payload_extra={
                        "artifact_digest": "a" * 64,
                        "deployment_environment": "staging",
                    },
                ),
            )
        ],
    )
    page = await _single_page_sweep(_adapter(ci_cd_source_adapter, preset), session)
    assert [record.record_id for record in page.records] == ["ci-1", "ci-2"]
    attempts = [record.payload["payload"]["attempt"] for record in page.records]
    statuses = [record.payload["payload"]["status"] for record in page.records]
    assert attempts == [1, 2]
    assert statuses == ["failed", "succeeded"]
    assert page.records[1].payload["payload"]["artifact_digest"] == "a" * 64


# ---------------------------------------------------------------------------
# OF-04: duplicate id, changed digest, out-of-order page.
# ---------------------------------------------------------------------------


async def test_identical_duplicate_is_idempotent_across_pages() -> None:
    preset = _preset("rum-stream", "rum_events")
    first = _rum_event("dup-1")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(first, cursor="page-2"), _page(dict(first), cursor=None)],
    )
    adapter = _adapter(rum_source_adapter, preset)
    await adapter.discover(session)
    checkpoint: SourceCheckpoint | None = None
    seen: list[str] = []
    for _ in range(2):
        page = await adapter.extract(session, checkpoint)
        seen.extend(record.record_id for record in page.records)
        checkpoint = page.checkpoint
    assert seen == ["dup-1"]


async def test_changed_digest_for_a_known_id_is_a_conflict_not_an_overwrite() -> None:
    preset = _preset("rum-stream", "rum_events")
    first = _rum_event("dup-2")
    changed = _rum_event("dup-2", payload_extra={"page": "/cart"})
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(first, cursor="page-2"), _page(changed, cursor=None)],
    )
    adapter = _adapter(rum_source_adapter, preset)
    await adapter.discover(session)
    checkpoint = (await adapter.extract(session, None)).checkpoint
    with pytest.raises(EventIdentityConflictError):
        await adapter.extract(session, checkpoint)


async def test_out_of_order_arrival_does_not_skip_a_durable_event() -> None:
    preset = _preset("rum-stream", "rum_events")
    later = _rum_event("order-2", offset_seconds=60)
    earlier = _rum_event("order-1", offset_seconds=0)
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(later, cursor="page-2"), _page(earlier, cursor=None)],
    )
    adapter = _adapter(rum_source_adapter, preset)
    await adapter.discover(session)
    checkpoint: SourceCheckpoint | None = None
    seen: list[str] = []
    for _ in range(2):
        page = await adapter.extract(session, checkpoint)
        seen.extend(record.record_id for record in page.records)
        checkpoint = page.checkpoint
    assert seen == ["order-2", "order-1"]


# ---------------------------------------------------------------------------
# OF-05: 429, expired retention window, breaking schema.
# ---------------------------------------------------------------------------


async def test_rate_limited_status_raises_typed_lag_without_advancing_checkpoint() -> (
    None
):
    preset = _preset("rum-stream", "rum_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(status="rate_limited", retry_after_seconds=30)],
    )
    adapter = _adapter(rum_source_adapter, preset)
    await adapter.discover(session)
    with pytest.raises(FeedBackpressureError) as caught:
        await adapter.extract(session, None)
    assert caught.value.retry_after_seconds == 30


async def test_retention_expired_status_raises_typed_expiry() -> None:
    preset = _preset("rum-stream", "rum_events")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[_page(status="retention_expired")],
    )
    adapter = _adapter(rum_source_adapter, preset)
    await adapter.discover(session)
    with pytest.raises(FeedRetentionExpiredError):
        await adapter.extract(session, None)


async def test_breaking_schema_quarantines_with_zero_writes_and_zero_checkpoint_advance() -> (
    None
):
    preset = _preset("rum-stream", "rum_events")
    current_descriptor = _tool_descriptor(preset.tool)
    prior_contract = validate_live_tool_contract(
        {"tools": [_tool_descriptor(preset.tool, extra_required="legacy_field")]},
        tool_name=preset.tool,
    ).schema_contract
    session = FakeEventSession(
        descriptor=current_descriptor, pages=[_page(_rum_event("rum-3"))]
    )
    adapter = _adapter(rum_source_adapter, preset, descriptor=current_descriptor)
    sink = InMemorySink()
    target = SyncTarget(CONNECTOR, sink, max_pages=1, schema_contract=prior_contract)
    with pytest.raises(SchemaDriftQuarantined):
        await sync_stream(session, adapter, target)
    assert sink.batches == {}
    assert (
        await sink.source_status(CONNECTOR, "rum-stream")
    ).accepted_checkpoint is None


# ---------------------------------------------------------------------------
# OF-06: restart after an accepted page with a contributor-owned graph.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "OF-06 is opt-in acceptance against a contributor-owned graph "
        "(SDK-OBSERVABILITY-FEEDS spec, Portable contribution and completion). "
        "NOT RUN: no such environment is provisioned in this suite."
    )
)
async def test_restart_replay_against_a_live_graph_is_exactly_once() -> None:
    raise AssertionError("opt-in acceptance test; never executed offline")


# ---------------------------------------------------------------------------
# Envelope, identity and construction units.
# ---------------------------------------------------------------------------


def test_envelope_refuses_missing_identity_instead_of_patching_it() -> None:
    fields = _rum_event("")
    fields.pop("provider_event_id")
    payload = fields.pop("payload")
    with pytest.raises(ValueError, match="provider_event_id"):
        EventEnvelope(
            **fields,
            feed_kind=FeedKind.RUM,
            payload=payload,
            payload_digest=compute_payload_digest(payload),
        )


def test_envelope_refuses_impossible_time_order() -> None:
    fields = _rum_event("rum-bad-time")
    payload = fields.pop("payload")
    fields["ingest_time"] = _T0.isoformat()
    fields["source_observed_time"] = (_T0 + timedelta(seconds=5)).isoformat()
    with pytest.raises(ValueError, match="ingest_time"):
        EventEnvelope(
            **fields,
            feed_kind=FeedKind.RUM,
            payload=payload,
            payload_digest=compute_payload_digest(payload),
        )


def test_identity_tracker_classifies_new_duplicate_and_conflict() -> None:
    tracker = EventIdentityTracker()
    assert tracker.classify("a", "digest-1") is EventIdentityOutcome.NEW
    assert tracker.classify("a", "digest-1") is EventIdentityOutcome.DUPLICATE
    with pytest.raises(EventIdentityConflictError):
        tracker.classify("a", "digest-2")


def test_event_feed_adapter_rejects_unpinned_construction_and_unsupported_presets() -> (
    None
):
    preset = _preset("rum-stream", "rum_events")
    with pytest.raises(ValueError, match="pinned"):
        rum_source_adapter(
            preset, connector="", tool_schema_sha256="", mapping_reference=""
        )
    reconciling = preset.model_copy(
        update={"reconcile_path": "live", "authoritative_path": "authoritative"}
    )
    with pytest.raises(ValueError, match="do not support"):
        rum_source_adapter(
            reconciling,
            connector=CONNECTOR,
            tool_schema_sha256="a" * 64,
            mapping_reference=f"manifest:{CONNECTOR}#schema_mappings/Event",
        )


async def test_reconcile_is_refused_for_append_only_event_feeds() -> None:
    preset = _preset("rum-stream", "rum_events")
    adapter = _adapter(rum_source_adapter, preset)
    session = FakeEventSession(descriptor=_tool_descriptor(preset.tool), pages=[])
    with pytest.raises(SourceContractError, match="reconcile"):
        await adapter.reconcile(session, frozenset())


def test_describe_names_the_feed_specific_kind() -> None:
    preset = _preset("audit-stream", "audit_events")
    adapter = _adapter(security_audit_source_adapter, preset)
    descriptor = adapter.describe()
    assert descriptor.kind == adapter.kind == "event_feed:security_audit"
    assert descriptor.pagination == ("cursor",)
