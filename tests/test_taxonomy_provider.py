"""Provider-specific requests use bounded, admitted, identity-checked pages."""

import json
from contextlib import asynccontextmanager

import pytest

from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.taxonomy.provider import (
    TaxonomyProvider,
    TaxonomyProviderError,
)
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "identifier", "body", "expected_path", "parent"),
    [
        (
            "ncbi",
            "9606",
            {
                "reports": [
                    {
                        "taxonomy": {
                            "tax_id": 9606,
                            "rank": "SPECIES",
                            "current_scientific_name": {"name": "Homo sapiens"},
                            "parents": [1, 9605],
                        }
                    }
                ]
            },
            "/taxonomy/taxon/9606/dataset_report",
            "NCBITaxon:9605",
        ),
        (
            "gbif",
            "123",
            {
                "key": 123,
                "scientificName": "Canis lupus",
                "rank": "SPECIES",
                "parentKey": 122,
            },
            "/species/123",
            "GBIF:122",
        ),
    ],
)
async def test_reads_real_provider_shapes(
    provider, identifier, body, expected_path, parent
):
    admitted = []

    @asynccontextmanager
    async def quota(name):
        admitted.append(name)
        yield

    with ScriptedHttpServer(ScriptedResponse(body=json.dumps(body).encode())) as server:
        source = TaxonomyProvider(
            provider=provider,
            http=HttpClientOptions(
                base_url=server.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            max_bytes=65536,
        )
        rows = await source.read([identifier], max_records=1)
        assert rows[0].parent_term_curie == parent
        assert server.requests[0].path == expected_path
        assert admitted == [provider]
        with pytest.raises(ValueError):
            await source.read([identifier, identifier], max_records=1)
        assert len(server.requests) == 1


@pytest.mark.asyncio
async def test_rejects_mismatched_or_oversized_provider_data():
    @asynccontextmanager
    async def quota(name):
        yield

    with ScriptedHttpServer(
        ScriptedResponse(body=b'{"key":2,"scientificName":"name"}'),
        ScriptedResponse(body=b"x" * 100),
    ) as server:
        source = TaxonomyProvider(
            provider="gbif",
            http=HttpClientOptions(
                base_url=server.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            max_bytes=50,
        )
        for _ in range(2):
            with pytest.raises(TaxonomyProviderError):
                await source.read(["1"], max_records=1)
