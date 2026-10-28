"""Account adapters bind served reads and CSV imports to one account."""

import hashlib
import json
from dataclasses import replace

import pytest
from epistemic_graph.generated.source_ingestion import SourceIngestionMode
from fastmcp import FastMCP
from test_finance_csv_import import _CONTEXT, _CSV, _MAPPING

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.finance.account_source import (
    AccountSourceAdapter,
    AccountSourceKind,
)
from agent_connector_sdk.finance.csv_source import (
    csv_activity_preset,
    register_csv_activity_tool,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport

POSITION = {
    "symbol": "ABC",
    "qty": 1.0,
    "avg_entry_price": 2.0,
    "current_price": 3.0,
    "unrealized_pnl": 1.0,
    "side": "long",
    "exchange": "alpaca",
}
ACCOUNT = {
    "account_id": "acct-1",
    "currency": "USD",
    "exchange": "alpaca",
    "equity": 10.0,
    "cash": 9.0,
    "buying_power": 8.0,
    "margin_used": 0.0,
    "positions": [POSITION],
}


def _server(record):
    server = FastMCP("finance")

    @server.tool()
    def read():
        return [record]

    return server


def _adapter(kind, id_field):
    preset = ToolPreset(
        name="account",
        server="finance",
        tool="read",
        id_field=id_field,
        params_style="args",
    )
    return AccountSourceAdapter(
        McpToolSourceAdapter(
            preset,
            connector="finance",
            mapping_reference="connector:finance#mappings/Account",
        ),
        account_kind=kind,
        tenant_id="tenant-1",
        account_id="acct-1",
    )


@pytest.mark.spec("SDK-FINANCE-SOURCES-R004.1")
async def test_snapshot_and_position_validate_before_sink():
    position_id = hashlib.sha256(json.dumps(["acct-1", "ABC"]).encode()).hexdigest()
    for kind, record, field in (
        (AccountSourceKind.ACCOUNT, ACCOUNT, "account_id"),
        (
            AccountSourceKind.POSITION,
            {**POSITION, "account_id": "acct-1", "position_id": position_id},
            "position_id",
        ),
    ):
        adapter, sink = _adapter(kind, field), InMemorySink()
        async with McpTransport().session(
            TransportEndpoint(in_process=_server(record))
        ) as session:
            await adapter.discover(session)
            assert (
                await adapter.extract(session, None)
            ).mode is SourceIngestionMode.DELTA
            result = await sync_stream(
                session, adapter, SyncTarget("finance", sink, max_pages=1)
            )
            assert result.accepted == 1
            with pytest.raises(SourceContractError, match="complete reconciliation"):
                await adapter.reconcile(session, frozenset())
        assert next(iter(sink.batches.values())).records[0].record_id == record[field]


@pytest.mark.spec("SDK-FINANCE-SOURCES-R004.1")
async def test_wrong_account_and_nonfinite_position_refuse_before_sink():
    for record in (
        {**ACCOUNT, "account_id": "other"},
        {**ACCOUNT, "positions": [{**POSITION, "qty": float("nan")}]},
    ):
        adapter, sink = (
            _adapter(AccountSourceKind.ACCOUNT, "account_id"),
            InMemorySink(),
        )
        async with McpTransport().session(
            TransportEndpoint(in_process=_server(record))
        ) as session:
            with pytest.raises(MalformedSourceDataError):
                await sync_stream(
                    session, adapter, SyncTarget("finance", sink, max_pages=1)
                )
        assert not sink.batches


@pytest.mark.spec("SDK-FINANCE-SOURCES-R004.1")
async def test_csv_source_reimport_preserves_scoped_activity_ids():
    server = FastMCP("finance")
    context = replace(_CONTEXT, provider="alpaca", source_id="alpaca-csv-activities")
    register_csv_activity_tool(
        server, name="csv_activities", content=_CSV, mapping=_MAPPING, context=context
    )
    preset = csv_activity_preset(
        stream=context.source_id, server="finance", tool="csv_activities"
    )
    adapter = AccountSourceAdapter(
        McpToolSourceAdapter(
            preset,
            connector="finance",
            mapping_reference="connector:finance#mappings/Activity",
        ),
        account_kind=AccountSourceKind.ACTIVITY,
        tenant_id=context.tenant_id,
        account_id=context.account_id,
    )
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        await adapter.discover(session)
        first = await adapter.extract(session, None)
        second = await adapter.extract(session, first.checkpoint)
    assert [r.record_id for r in first.records] == [r.record_id for r in second.records]
    assert len(first.records) == 2
    other = AccountSourceAdapter(
        McpToolSourceAdapter(
            preset,
            connector="finance",
            mapping_reference="connector:finance#mappings/Activity",
        ),
        account_kind=AccountSourceKind.ACTIVITY,
        tenant_id="other-tenant",
        account_id=context.account_id,
    )
    sink = InMemorySink()
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        with pytest.raises(MalformedSourceDataError):
            await sync_stream(session, other, SyncTarget("finance", sink, max_pages=1))
    assert not sink.batches
