"""Paper search crosses served MCP, shared EG quota, and controlled HTTP."""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client, FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401

from scion_sdk.adapters.paper_models import (
    FieldEvidence,
    PaperQuery,
    ProviderReference,
)
from scion_sdk.adapters.paper_provider import (
    PaperProvider,
    ProviderFailure,
    ProviderPage,
    ProviderPaper,
)
from scion_sdk.adapters.paper_quota import PaperQuotaPolicy, SharedPaperQuota
from scion_sdk.adapters.paper_search import (
    PaperSearchService,
    ProviderBinding,
)
from scion_sdk.adapters.paper_tool import register_paper_search_tool
from scion_sdk.http.client import create_async_http_client
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import RetryPolicy
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


class _HttpProvider:
    def __init__(self, name, endpoint):
        self.name = name
        self.endpoint = endpoint

    async def search(self, query, cursor):
        options = HttpClientOptions(
            base_url=self.endpoint,
            pin_egress=True,
            allow_loopback=True,
            retry=RetryPolicy(max_attempts=1),
        )
        async with create_async_http_client(options) as client:
            response = await client.get("/search")
        if response.status_code != 200:
            raise ProviderFailure("provider_failed")
        data = response.json()
        reference = ProviderReference(provider_id=self.name, record_id=data["id"])
        evidence = FieldEvidence(
            provider_id=self.name, source_id=data["id"], location="title"
        )
        return ProviderPage(
            records=(
                ProviderPaper(
                    reference=reference,
                    title=data["title"],
                    doi=data["doi"],
                    field_provenance={"title": (evidence,)},
                ),
            )
        )


async def _exercise(first_url, second_url):
    engine = await scoped_client(
        ["kv:read", "kv:write", "kv:shared:read", "kv:shared:write"]
    )
    try:
        quota = SharedPaperQuota(engine)
        bindings = {
            name: ProviderBinding(
                provider=_HttpProvider(name, url),
                quota=PaperQuotaPolicy(
                    provider_id=name,
                    credential_group=f"{name}-public",
                    policy_revision="v1",
                    minimum_spacing_ns=1,
                ),
                retries=0,
            )
            for name, url in (("first", first_url), ("second", second_url))
        }
        assert all(
            isinstance(binding.provider, PaperProvider) for binding in bindings.values()
        )

        async def allow(query, ctx):
            return query.tenant == "allowed" and ctx is not None

        server = FastMCP("papers")
        register_paper_search_tool(
            server, PaperSearchService(bindings, quota=quota, authorize=allow)
        )
        async with Client(server) as client:
            query = PaperQuery(
                tenant="allowed",
                query="test",
                provider_ids=("first", "second"),
                schema_revision="v1",
            )
            result = await client.call_tool(
                "paper_search", {"query": query.model_dump(mode="json")}
            )
            denied = await client.call_tool(
                "paper_search",
                {
                    "query": query.model_copy(update={"tenant": "denied"}).model_dump(
                        mode="json"
                    )
                },
            )
        return result.structured_content, denied.structured_content
    finally:
        await engine.close()


def test_served_search_reports_partial_and_denies_other_tenant(live_ingest):  # noqa: F811
    body = json.dumps(
        {"id": "p1", "title": "Example", "doi": "10.1234/example"}
    ).encode()
    with (
        ScriptedHttpServer(
            ScriptedResponse(body=body, headers={"Content-Type": "application/json"})
        ) as first,
        ScriptedHttpServer(
            ScriptedResponse(status=503, body=b"private error")
        ) as second,
    ):
        result, denied = asyncio.run_coroutine_threadsafe(
            _exercise(first.base_url, second.base_url), live_ingest._loop
        ).result(30)
        assert result["completeness"] == "partial", result
        assert result["records"][0]["canonical_id"] == "doi:10.1234/example"
        assert [report["outcome"] for report in result["reports"]] == ["ok", "failed"]
        assert denied["completeness"] == "failed"
        assert all(report["reason"] == "unauthorized" for report in denied["reports"])
        assert len(first.requests) == len(second.requests) == 1
        assert "private error" not in json.dumps(result)
