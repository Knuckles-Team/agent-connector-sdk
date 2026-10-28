"""Read host-admitted GBIF and iNaturalist occurrence records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, Literal

from agent_connector_sdk.earth_observations.records import OrganismObservation
from agent_connector_sdk.http._bounded_provider import _BoundedProvider, _fetch
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.taxonomy.provider import _valid_id

OccurrenceProviderName = Literal["gbif", "inaturalist"]


class OccurrenceProviderError(RuntimeError):
    """A bounded occurrence request could not be accepted."""


class OccurrenceProvider(_BoundedProvider[OccurrenceProviderName]):
    """Read explicit IDs under a host's egress, quota and license policy."""

    def __init__(
        self,
        *,
        provider: OccurrenceProviderName,
        http: HttpClientOptions,
        quota: Callable[[str], AbstractAsyncContextManager[Any]],
        license_admitted: Callable[[str], bool],
        max_bytes: int,
    ) -> None:
        if provider not in ("gbif", "inaturalist"):
            raise ValueError("invalid occurrence provider policy")
        super().__init__(provider=provider, http=http, quota=quota, max_bytes=max_bytes)
        self.license_admitted = license_admitted

    async def read(
        self, identifiers: Sequence[str], *, tenant: str, source: str, max_records: int
    ) -> tuple[OrganismObservation, ...]:
        if (
            not tenant
            or not source
            or max_records < 1
            or len(identifiers) > max_records
        ):
            raise ValueError("invalid occurrence request")
        if len(set(identifiers)) != len(identifiers) or any(
            not _valid_id(item) for item in identifiers
        ):
            raise ValueError("invalid occurrence identifiers")
        records = []
        for identifier in identifiers:
            async with self.quota(self.provider):
                records.append(
                    await self._read_one(identifier, tenant=tenant, source=source)
                )
        return tuple(records)

    async def _read_one(
        self, identifier: str, *, tenant: str, source: str
    ) -> OrganismObservation:
        try:
            return await self._read_record(identifier, tenant=tenant, source=source)
        except Exception:
            raise OccurrenceProviderError(
                "occurrence provider response refused"
            ) from None

    async def _read_record(
        self, identifier: str, *, tenant: str, source: str
    ) -> OrganismObservation:
        path = (
            f"occurrence/{identifier}"
            if self.provider == "gbif"
            else f"observations/{identifier}"
        )
        payload = await _fetch(self.http, path, self.max_bytes)
        data = json.loads(payload)
        raw = _source_record(self.provider, identifier, data)
        license_tag = raw["license"]
        if (
            not isinstance(license_tag, str)
            or not license_tag
            or not self.license_admitted(license_tag)
        ):
            raise ValueError("occurrence license not admitted")
        return OrganismObservation(
            tenant_id=tenant,
            source_id=source,
            provider=self.provider,
            source_event_id=identifier,
            event_time_utc=_timestamp(raw["time"]),
            observed_at_utc=datetime.now(UTC),
            license_tag=license_tag,
            source_digest=hashlib.sha256(payload).hexdigest(),
            taxon_id=raw["taxon_id"],
            scientific_name=raw["scientific_name"],
            place_id=f"{self.provider}:occurrence:{identifier}:location",
            latitude=raw["latitude"],
            longitude=raw["longitude"],
            individual_count=raw["count"],
            basis_of_record=raw["basis"],
        )


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("explicit observation time required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("observation timezone required")
    return result.astimezone(UTC)


def _source_record(
    provider: OccurrenceProviderName, identifier: str, data: Any
) -> dict[str, Any]:
    if provider == "gbif":
        return _gbif_record(identifier, data)
    return _inat_record(identifier, data)


def _gbif_record(identifier: str, data: Any) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or str(data.get("key")) != identifier
        or not _valid_id(str(data.get("taxonKey")))
    ):
        raise ValueError("GBIF identity mismatch")
    return {
        "time": data.get("eventDate"),
        "license": data.get("license"),
        "taxon_id": f"GBIF:{data['taxonKey']}",
        "scientific_name": data.get("scientificName"),
        "latitude": data.get("decimalLatitude"),
        "longitude": data.get("decimalLongitude"),
        "count": data.get("individualCount"),
        "basis": data.get("basisOfRecord"),
    }


def _inat_record(identifier: str, data: Any) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("results"), list)
        or len(data["results"]) != 1
    ):
        raise ValueError("invalid iNaturalist response")
    item = data["results"][0]
    if str(item["id"]) != identifier or not _valid_id(str(item["taxon"]["id"])):
        raise ValueError("iNaturalist identity mismatch")
    latitude, longitude = item["location"].split(",", 1)
    return {
        "time": item.get("time_observed_at"),
        "license": item.get("license_code"),
        "taxon_id": f"iNaturalist:{item['taxon']['id']}",
        "scientific_name": item["taxon"].get("name"),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "count": item.get("number_of_individuals"),
        "basis": "INATURALIST_OBSERVATION",
    }
