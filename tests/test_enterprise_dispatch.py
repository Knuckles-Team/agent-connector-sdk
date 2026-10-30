"""Enterprise dispatcher keeps exact caller, company and declared schema bounds."""

import pytest

from agent_connector_sdk.identity import ActorContext, ActorType
from agent_connector_sdk.mcp.enterprise_tools import register_enterprise_tools
from agent_connector_sdk.vendor_extractors.enterprise_contract import (
    EnterpriseCapability,
    EnterpriseOperation,
    EnterpriseResult,
    ListAccounts,
    ReadInvoice,
)
from agent_connector_sdk.vendor_extractors.enterprise_dispatch import (
    EnterpriseAuthority,
    EnterpriseDispatcher,
    EnterpriseReader,
    EnterpriseWriteAdmission,
    EnterpriseWriteTarget,
    enterprise_schema_binding,
)


def actor() -> ActorContext:
    return ActorContext(
        actor_id="principal",
        tenant_id="tenant",
        actor_type=ActorType.HUMAN,
        authenticated=True,
    )


def request() -> EnterpriseOperation:
    return EnterpriseOperation(
        request_id="request",
        tenant="tenant",
        company_id="company",
        contract_revision="v1",
        authority="principal",
        parameters=ListAccounts(limit=10),
    )


class Authority:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    async def authorize(self, actor, request):
        return self.allow


class Reader:
    def __init__(self, connector: str) -> None:
        self.connector = connector
        self.calls = []

    async def read(self, request):
        self.calls.append(request)
        return EnterpriseResult(
            request_id=request.request_id,
            tenant=request.tenant,
            company_id=request.company_id,
            connector=self.connector,
            contract_revision=request.contract_revision,
            operation=request.parameters.operation,
            outcome="ok",
            backend_receipt="fixture:receipt",
        )


def dispatcher(connector="erp", *, allow=True):
    reader = Reader(connector)
    cap = EnterpriseCapability(
        connector=connector,
        connector_version="1",
        contract_revision="v1",
        company_ids=("company",),
        operations=(enterprise_schema_binding("list_accounts"),),
    )
    return EnterpriseDispatcher(cap, authority=Authority(allow), reader=reader), reader


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.33")
@pytest.mark.spec("SCION-SOURCE-INGEST-R006.36")
@pytest.mark.asyncio
async def test_explicit_backend_swaps_preserve_request_and_result():
    first, first_reader = dispatcher("first")
    second, second_reader = dispatcher("second")
    one = await first.execute(actor(), request())
    two = await second.execute(actor(), request())
    assert one.outcome == two.outcome == "ok"
    assert one.operation_digest == two.operation_digest
    assert (one.connector, two.connector) == ("first", "second")
    assert first_reader.calls == second_reader.calls == [request()]


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.35")
@pytest.mark.asyncio
async def test_wrong_scope_and_unsupported_refuse_before_reader():
    client, reader = dispatcher()
    wrong = request().model_copy(update={"company_id": "other"})
    assert (await client.execute(actor(), wrong)).reason == "unauthorized"
    unsupported = request().model_copy(
        update={"parameters": ReadInvoice(invoice_id="a")}
    )
    assert (
        await client.execute(actor(), unsupported)
    ).reason == "unsupported_operation"
    denied, denied_reader = dispatcher(allow=False)
    assert (await denied.execute(actor(), request())).reason == "unauthorized"
    assert not reader.calls and not denied_reader.calls


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.34")
@pytest.mark.asyncio
async def test_factory_serves_two_connectors_and_refuses_denied_calls():
    from fastmcp import Client

    from agent_connector_sdk.identity import use_actor
    from agent_connector_sdk.mcp.server import create_mcp_server

    first, first_reader = dispatcher("first")
    second, second_reader = dispatcher("second")
    _, first_server, _ = create_mcp_server(
        "first",
        version="1",
        command_args=["--transport", "stdio"],
        enterprise_dispatcher=first,
    )
    _, second_server, _ = create_mcp_server(
        "second",
        version="1",
        command_args=["--transport", "stdio"],
        enterprise_dispatcher=second,
    )
    with use_actor(actor()):
        async with Client(first_server) as client:
            one = await client.call_tool(
                "enterprise_operation", {"request": request().model_dump(mode="json")}
            )
        async with Client(second_server) as client:
            two = await client.call_tool(
                "enterprise_operation", {"request": request().model_dump(mode="json")}
            )
    assert one.data["outcome"] == two.data["outcome"] == "ok"
    assert one.data["operation_digest"] == two.data["operation_digest"]
    assert (one.data["connector"], two.data["connector"]) == ("first", "second")
    assert len(first_reader.calls) == len(second_reader.calls) == 1
    async with Client(first_server) as client:
        denied = await client.call_tool(
            "enterprise_operation", {"request": request().model_dump(mode="json")}
        )
    assert denied.data["reason"] == "unauthorized"
    assert len(first_reader.calls) == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.33")
@pytest.mark.spec("SCION-SOURCE-INGEST-R006.36")
@pytest.mark.asyncio
async def test_invoice_effect_requires_admitted_writer_and_durable_receipt(tmp_path):
    from test_writeback_process_restart import _reference_change_set

    from agent_connector_sdk.testing.writeback_audit import InMemoryAuditReservation
    from agent_connector_sdk.vendor_extractors.enterprise_contract import CreateInvoice
    from agent_connector_sdk.writeback.connector import DurableWritableConnector
    from agent_connector_sdk.writeback.durable_ledger import FileWriteBackLedger
    from agent_connector_sdk.writeback.durable_transport import FileWriteBackTransport

    patch = {
        "operation": "create_invoice",
        "company_id": "company",
        "invoice": {"company": "company", "customer": "example"},
    }
    change = _reference_change_set().model_copy(
        update={
            "actor": "principal",
            "desired_patch": patch,
            "field_scope": list(patch),
            "field_provenance": {key: "fixture" for key in patch},
        }
    )
    change = change.model_copy(update={"change_set_digest": change.canonical_digest()})
    ledger = FileWriteBackLedger(tmp_path / "ledger")
    transport = FileWriteBackTransport(tmp_path / "source")
    transport.seed(change.entity_id, "v1", {})
    writable = DurableWritableConnector(
        change.connector_id, transport, ledger, audit=InMemoryAuditReservation()
    )
    await writable.register(change)
    cap = EnterpriseCapability(
        connector=change.connector_id,
        connector_version="1",
        contract_revision="v1",
        company_ids=("company", "other"),
        operations=(enterprise_schema_binding("create_invoice"),),
    )
    client = EnterpriseDispatcher(
        cap,
        authority=Authority(),
        reader=Reader(change.connector_id),
    )
    req = EnterpriseOperation(
        request_id="write",
        tenant=change.tenant_id,
        company_id="other",
        contract_revision="v1",
        authority="principal",
        parameters=CreateInvoice(change_set=change),
    )
    user = ActorContext(
        actor_id="principal",
        tenant_id=change.tenant_id,
        actor_type=ActorType.HUMAN,
        authenticated=True,
    )
    assert (await client.execute(user, req)).reason == "invalid_request"
    result = await client.execute(
        user, req.model_copy(update={"company_id": "company"})
    )
    assert result.reason == "unsupported_operation"
    assert (await transport.read_current(change)).source_version == "v1"

    class Admission:
        async def admit(self, actor, request, capability):
            return EnterpriseWriteTarget(writable, ledger)

    admitted = EnterpriseDispatcher(
        cap,
        authority=Authority(),
        reader=Reader(change.connector_id),
        write_admission=Admission(),
    )
    wrong_patch = {
        **change.desired_patch,
        "invoice": {"company": "other", "customer": "example"},
    }
    wrong_change = change.model_copy(update={"desired_patch": wrong_patch})
    wrong_change = wrong_change.model_copy(
        update={"change_set_digest": wrong_change.canonical_digest()}
    )
    wrong_req = req.model_copy(
        update={
            "company_id": "company",
            "parameters": CreateInvoice(change_set=wrong_change),
        }
    )
    assert (await admitted.execute(user, wrong_req)).reason == "invalid_request"
    assert (await transport.read_current(change)).source_version == "v1"
    result = await admitted.execute(
        user, req.model_copy(update={"company_id": "company"})
    )
    assert result.outcome == "ok" and result.effect_receipt is not None
    assert result.effect_receipt.change_set_digest == change.change_set_digest
    assert (await transport.read_current(change)).source_version == "v1+1"


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.34")
def test_public_registration_and_authority_ports_are_exposed():
    assert callable(register_enterprise_tools)
    assert EnterpriseAuthority is not EnterpriseReader
    assert EnterpriseWriteAdmission is not EnterpriseReader


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.36")
@pytest.mark.asyncio
async def test_source_adapter_binds_enterprise_receipts_and_refuses_failures():
    from agent_connector_sdk.adapters.mcp_tool_records import (
        _validate_platform_binding,
        raw_records,
    )
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.ports.errors import SourceContractError

    handler, _ = dispatcher()
    result = (await handler.execute(actor(), request())).model_dump(mode="json")
    preset = ToolPreset(
        name="accounts",
        server="erp",
        tool="enterprise_operation",
        records_path="accounts",
        result_contract="enterprise",
    )
    arguments = {"request": request().model_dump(mode="json")}
    await _validate_platform_binding(preset, arguments, result)
    assert raw_records(preset, result) == []
    with pytest.raises(SourceContractError):
        await _validate_platform_binding(
            preset, arguments, {**result, "company_id": "other"}
        )
    refused = (
        await handler.execute(
            actor(), request().model_copy(update={"company_id": "other"})
        )
    ).model_dump(mode="json")
    with pytest.raises(SourceContractError):
        raw_records(preset, refused)


@pytest.mark.asyncio
async def test_served_enterprise_source_reaches_sink_and_refusal_keeps_it_empty():
    from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
    from agent_connector_sdk.identity import use_actor
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.mcp.server import create_mcp_server
    from agent_connector_sdk.ports.errors import SourceContractError
    from agent_connector_sdk.ports.session import TransportEndpoint
    from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
    from agent_connector_sdk.testing.sinks import InMemorySink
    from agent_connector_sdk.transports.mcp import McpTransport
    from agent_connector_sdk.vendor_extractors.enterprise_contract import AccountRecord

    class AccountReader(Reader):
        async def read(self, req):
            result = await super().read(req)
            return result.model_copy(
                update={
                    "accounts": (
                        AccountRecord(
                            source_id="account",
                            account_code="100",
                            label="Cash",
                            account_kind="asset",
                            currency="USD",
                        ),
                    )
                }
            )

    cap = EnterpriseCapability(
        connector="erp",
        connector_version="1",
        contract_revision="v1",
        company_ids=("company",),
        operations=(enterprise_schema_binding("list_accounts"),),
    )
    preset = ToolPreset(
        name="accounts",
        server="erp",
        tool="enterprise_operation",
        params_style="args",
        arguments={"request": request().model_dump(mode="json")},
        records_path="accounts",
        result_contract="enterprise",
        id_field="source_id",
    )
    for allowed in (True, False):
        handler = EnterpriseDispatcher(
            cap, authority=Authority(allowed), reader=AccountReader("erp")
        )
        _, server, _ = create_mcp_server(
            "erp", version="1", command_args=[], enterprise_dispatcher=handler
        )
        adapter = McpToolSourceAdapter(
            preset, connector="erp", mapping_reference="connector:erp#mappings/Account"
        )
        sink = InMemorySink()
        with use_actor(actor()):
            async with McpTransport().session(
                TransportEndpoint(in_process=server)
            ) as session:
                if allowed:
                    await sync_stream(
                        session, adapter, SyncTarget("erp", sink, max_pages=1)
                    )
                else:
                    with pytest.raises(SourceContractError):
                        await sync_stream(
                            session, adapter, SyncTarget("erp", sink, max_pages=1)
                        )
        if allowed:
            assert [
                record.record_id
                for batch in sink.batches.values()
                for record in batch.records
            ] == ["account"]
        else:
            assert not sink.batches


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.35")
@pytest.mark.asyncio
async def test_oversized_enterprise_effect_refuses_before_admission():
    from test_writeback_process_restart import _reference_change_set

    from agent_connector_sdk.vendor_extractors.enterprise_contract import CreateInvoice

    change = _reference_change_set().model_copy(
        update={
            "desired_patch": {
                "invoice": {"company": "company", "customer": "x" * 1_100_000},
                "company_id": "company",
                "operation": "create_invoice",
            }
        }
    )
    change = change.model_copy(update={"change_set_digest": change.canonical_digest()})
    req = EnterpriseOperation(
        request_id="oversized",
        tenant=change.tenant_id,
        company_id="company",
        contract_revision="v1",
        authority="principal",
        parameters=CreateInvoice(change_set=change),
    )
    user = ActorContext(
        actor_id="principal",
        tenant_id=change.tenant_id,
        actor_type=ActorType.HUMAN,
        authenticated=True,
    )
    client, reader = dispatcher()
    assert (await client.execute(user, req)).reason == "invalid_request"
    assert not reader.calls
