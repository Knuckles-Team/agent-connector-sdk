"""Occurrence sources retain provider facts and refuse ambiguous records."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from agent_connector_sdk.earth_observations.occurrence import (
    OccurrenceProvider,
    OccurrenceProviderError,
)
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "body", "path", "taxon"),
    [
        (
            "gbif",
            {
                "key": 12,
                "taxonKey": 7,
                "scientificName": "Taxon",
                "eventDate": "2026-01-02T03:04:00Z",
                "license": "CC-BY",
                "decimalLatitude": 45.0,
                "decimalLongitude": -92.0,
                "basisOfRecord": "HUMAN_OBSERVATION",
            },
            "/occurrence/12",
            "GBIF:7",
        ),
        (
            "inaturalist",
            {
                "results": [
                    {
                        "id": 12,
                        "taxon": {"id": 7, "name": "Taxon"},
                        "time_observed_at": "2026-01-02T06:04:00+03:00",
                        "license_code": "CC-BY",
                        "location": "45,-92",
                    }
                ]
            },
            "/observations/12",
            "iNaturalist:7",
        ),
    ],
)
async def test_occurrence_read(provider, body, path, taxon):
    admitted = []

    @asynccontextmanager
    async def quota(name):
        admitted.append(name)
        yield

    with ScriptedHttpServer(ScriptedResponse(body=json.dumps(body).encode())) as server:
        client = OccurrenceProvider(
            provider=provider,
            http=HttpClientOptions(
                base_url=server.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            license_admitted=lambda tag: tag == "CC-BY",
            max_bytes=4096,
        )
        (record,) = await client.read(
            ["12"], tenant="tenant-a", source="observations", max_records=1
        )
        assert record.taxon_id == taxon
        assert record.event_time_utc == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
        assert record.individual_count is None
        assert (record.latitude, record.longitude) == (45.0, -92.0)
        assert server.requests[0].path == path
        assert admitted == [provider]


@pytest.mark.asyncio
async def test_ambiguous_time_and_unapproved_license_refused():
    @asynccontextmanager
    async def quota(name):
        yield

    base = {
        "key": 12,
        "taxonKey": 7,
        "scientificName": "Taxon",
        "eventDate": "2026-01-02",
        "license": "CC-BY",
        "decimalLatitude": 45.0,
        "decimalLongitude": -92.0,
        "basisOfRecord": "HUMAN_OBSERVATION",
    }
    invalid = {**base, "eventDate": "2026-01-02T03:04:00Z", "license": "not-admitted"}
    with ScriptedHttpServer(
        ScriptedResponse(body=json.dumps(base).encode()),
        ScriptedResponse(body=json.dumps(invalid).encode()),
    ) as server:
        client = OccurrenceProvider(
            provider="gbif",
            http=HttpClientOptions(
                base_url=server.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            license_admitted=lambda tag: tag == "CC-BY",
            max_bytes=4096,
        )
        for _ in range(2):
            with pytest.raises(OccurrenceProviderError):
                await client.read(
                    ["12"], tenant="tenant-a", source="observations", max_records=1
                )
