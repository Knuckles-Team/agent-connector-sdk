import asyncio
import hashlib
import json

import pytest
from epistemic_graph.connector_pack import (
    ConnectorPackArchiveBuilder,
    ConnectorPackClient,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind, PackProducer
from fastmcp import FastMCP
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog, _mutation_context
from test_event_feeds import CONNECTOR
from test_paper_search_served import _HttpProvider

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.adapters.paper_ingest_tool import (
    register_paper_provider_stream,
)
from agent_connector_sdk.adapters.paper_models import PaperQuery
from agent_connector_sdk.adapters.paper_provider import ProviderPage
from agent_connector_sdk.adapters.paper_quota import PaperQuotaPolicy, SharedPaperQuota
from agent_connector_sdk.adapters.paper_search import (
    PaperSearchService,
    ProviderBinding,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import McpTransportError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.transports.mcp import McpTransport


async def _strict_mapping(client):
    context = _mutation_context().model_copy(update={"tenant_id": TENANT})
    key = "paper-null-test:bind"
    await client._send(
        "ConnectorPack",
        {
            "op": {
                "op": "bind",
                "request": {
                    "context": context.model_copy(
                        update={"idempotency_key": key}
                    ).model_dump(mode="json"),
                    "connector": CONNECTOR,
                    "importer": "principal:sha256:"
                    + hashlib.sha256(PRINCIPAL.encode()).hexdigest(),
                },
            }
        },
        None,
        idempotency_key=key,
    )
    server = ConnectorPackEntryContent(
        kind=PackEntryKind.MCP_SERVER,
        uri=f"mcp-server://{CONNECTOR}",
        name=CONNECTOR,
        media_type="application/json",
        body=json.dumps({"name": CONNECTOR}).encode(),
    )
    resource = ConnectorPackEntryContent(
        kind=PackEntryKind.RESOURCE,
        uri="connector://resources",
        name="connector-resources",
        media_type="application/json",
        body=json.dumps(
            {
                "connector": CONNECTOR,
                "sources": [],
                "schema_mappings": {
                    "Event": {
                        "ontology_class": "Document",
                        "fields": {"abstract": "xsd:string"},
                    }
                },
            }
        ).encode(),
        output_schema=b'{"type":"object"}',
    )
    result = await ConnectorPackClient(client).import_pack(
        ConnectorPackArchiveBuilder.build(server, [resource]),
        connector=CONNECTOR,
        server_package_version="1.0.0",
        producer=PackProducer(name="paper-null-test", version="1"),
        catalog=_catalog(),
        context=context,
    )
    assert result.result == "imported"
    return context


async def exercise(url):
    engine = await scoped_client(["*"])
    try:
        context = await _strict_mapping(engine)

        async def authority(_connector):
            return _catalog(), context

        async def authorize(query, ctx):
            return query.tenant == "allowed" and ctx is not None

        policy = PaperQuotaPolicy(
            provider_id="arxiv",
            credential_group="arxiv-graph",
            policy_revision="v1",
            minimum_spacing_ns=1,
        )

        class Provider(_HttpProvider):
            async def search(self, query, cursor):
                page = await super().search(query, cursor)
                return ProviderPage(
                    records=page.records, cursor="1" if cursor is None else None
                )

        service = PaperSearchService(
            {"arxiv": ProviderBinding(Provider("arxiv", url), policy, retries=0)},
            quota=SharedPaperQuota(engine),
            authorize=authorize,
        )
        query = PaperQuery(
            tenant="allowed",
            query="graph",
            provider_ids=("arxiv",),
            schema_revision="v1",
            page_bound=1,
        )
        server = FastMCP("paper-graph")
        register_paper_provider_stream(
            server, service, query, name="paper_arxiv_ingest"
        )
        preset = ToolPreset(
            name="paper-arxiv",
            server=CONNECTOR,
            tool="paper_arxiv_ingest",
            id_field="id",
            records_path="records",
            params_style="args",
            params={"mode": "delta"},
            pagination="cursor",
            cursor_param="cursor",
            cursor_path="next",
            updated_since_param="state",
            checkpoint_path="checkpoint",
        )

        def adapter():
            return McpToolSourceAdapter(
                preset,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}#mappings/Event",
            )

        sink = EpistemicGraphSink(engine, authority)
        target = SyncTarget(CONNECTOR, sink, max_pages=1)
        async with McpTransport().session(
            TransportEndpoint(in_process=server)
        ) as session:
            first = await sync_stream(session, adapter(), target)
            before = await sink.source_status(CONNECTOR, "paper-arxiv")
            with pytest.raises(McpTransportError, match="paper_arxiv_ingest"):
                await sync_stream(session, adapter(), target)
            failed = await sink.source_status(CONNECTOR, "paper-arxiv")
            second = await sync_stream(session, adapter(), target)
        rows = await engine.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        return first, before, failed, second, rows
    finally:
        await engine.close()


def test_provider_failure_and_restart(live_ingest):  # noqa: F811
    def feed(paper):
        return json.dumps(
            {"id": paper, "title": "Graph " + paper, "doi": "10.1234/" + paper}
        ).encode()

    with ScriptedHttpServer(
        ScriptedResponse(
            body=feed("1234.5678"), headers={"Content-Type": "application/json"}
        ),
        ScriptedResponse(status=503, body=b"error"),
        ScriptedResponse(
            body=feed("9876.5432"), headers={"Content-Type": "application/json"}
        ),
    ) as server:
        first, before, failed, second, rows = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url), live_ingest._loop
        ).result(30)
        assert first.accepted == 1
        assert before.accepted_checkpoint == failed.accepted_checkpoint
        assert second.accepted == 1
        nodes = [
            row["n"] for row in rows if row["n"].get("source_stream") == "paper-arxiv"
        ]
        assert len(nodes) == 2, nodes
