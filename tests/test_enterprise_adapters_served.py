"""Two real served connectors swap behind one enterprise contract."""

import pytest
from test_enterprise_dispatch import (
    Authority,
    actor,
    request,
)

from agent_connector_sdk.vendor_extractors.enterprise_contract import (
    EnterpriseCapability,
    EnterpriseResult,
    ReadInvoice,
)
from agent_connector_sdk.vendor_extractors.enterprise_dispatch import (
    EnterpriseDispatcher,
    enterprise_schema_binding,
)


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.37")
@pytest.mark.asyncio
async def test_backend_swap_and_unsupported():
    import json

    from fastmcp import Client

    from agent_connector_sdk.http.client import create_async_http_client
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.http.retry import RetryPolicy
    from agent_connector_sdk.identity import use_actor
    from agent_connector_sdk.mcp.server import create_mcp_server
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )
    from agent_connector_sdk.vendor_extractors.enterprise_contract import AccountRecord

    class HttpReader:
        def __init__(self, connector, endpoint):
            self.connector = connector
            self.options = HttpClientOptions(
                base_url=endpoint,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            )

        async def read(self, req):
            async with create_async_http_client(self.options) as http:
                response = await http.get("/accounts")
                response.raise_for_status()
                accounts = tuple(
                    AccountRecord.model_validate(item)
                    for item in response.json()["accounts"]
                )
            return EnterpriseResult(
                request_id=req.request_id,
                tenant=req.tenant,
                company_id=req.company_id,
                connector=self.connector,
                contract_revision=req.contract_revision,
                operation="list_accounts",
                outcome="ok",
                accounts=accounts,
                backend_receipt="fixture:page",
            )

    body = json.dumps(
        {
            "accounts": [
                {
                    "source_id": "account",
                    "account_code": "100",
                    "label": "Cash",
                    "account_kind": "asset",
                    "currency": "USD",
                }
            ]
        }
    ).encode()
    with (
        ScriptedHttpServer(ScriptedResponse(body=body)) as backend_one,
        ScriptedHttpServer(ScriptedResponse(body=body)) as backend_two,
    ):
        servers = []
        for name, backend in (("one", backend_one), ("two", backend_two)):
            cap = EnterpriseCapability(
                connector=name,
                connector_version="1",
                contract_revision="v1",
                company_ids=("company",),
                operations=(enterprise_schema_binding("list_accounts"),),
            )
            handler = EnterpriseDispatcher(
                cap,
                authority=Authority(),
                reader=HttpReader(name, backend.base_url),
            )
            _, server, _ = create_mcp_server(
                name,
                version="1",
                command_args=["--transport", "stdio"],
                enterprise_dispatcher=handler,
            )
            servers.append(server)
        with use_actor(actor()):
            for server in servers:
                async with Client(server) as client:
                    result = await client.call_tool(
                        "enterprise_operation",
                        {"request": request().model_dump(mode="json")},
                    )
                    assert result.data["accounts"][0]["account_code"] == "100"
                    bad = request().model_copy(
                        update={"parameters": ReadInvoice(invoice_id="unknown")}
                    )
                    denied = await client.call_tool(
                        "enterprise_operation", {"request": bad.model_dump(mode="json")}
                    )
                    assert denied.data["reason"] == "unsupported_operation"
        assert len(backend_one.requests) == len(backend_two.requests) == 1
