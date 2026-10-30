import asyncio
import json

from fastmcp import FastMCP
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from source_graph_helpers import import_source_mapping, sync_failure_cycle
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR
from test_paper_search_served import _HttpProvider

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.adapters.paper_ingest_tool import (
    register_paper_provider_stream,
)
from scion_sdk.adapters.paper_models import PaperQuery
from scion_sdk.adapters.paper_provider import ProviderPage
from scion_sdk.adapters.paper_quota import PaperQuotaPolicy, SharedPaperQuota
from scion_sdk.adapters.paper_search import (
    PaperSearchService,
    ProviderBinding,
)
from scion_sdk.manifest.presets import ToolPreset
from scion_sdk.sinks.epistemic_graph import EpistemicGraphSink
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url):
    engine = await scoped_client(["*"])
    try:
        context = await import_source_mapping(
            engine,
            CONNECTOR,
            {
                "Event": {
                    "fields": {"abstract": "xsd:string"},
                    "ontology_class": "Document",
                }
            },
        )

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
        first, before, failed, second, _ = await sync_failure_cycle(
            server, sink, CONNECTOR, "paper-arxiv", "paper_arxiv_ingest", adapter
        )
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
