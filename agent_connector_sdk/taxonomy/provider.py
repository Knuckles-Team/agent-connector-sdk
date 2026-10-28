"""Bounded reads of explicitly admitted taxonomy identifiers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal

from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.taxonomy.records import (
    TaxonRecord,
    taxon_from_gbif,
    taxon_from_ncbi,
)

Provider = Literal["ncbi", "gbif"]
Quota = Callable[[Provider], AbstractAsyncContextManager[Any]]


def _valid_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and 1 <= len(value) <= 20
        and not value.startswith("0")
    )


class TaxonomyProviderError(RuntimeError):
    """A provider page could not be obtained or validated."""


class TaxonomyProvider:
    """Read admitted IDs under caller-supplied provider and quota policies."""

    def __init__(
        self,
        *,
        provider: Provider,
        http: HttpClientOptions,
        quota: Quota,
        max_bytes: int,
    ) -> None:
        if (
            provider not in ("ncbi", "gbif")
            or not http.pin_egress
            or http.retry.max_attempts != 1
            or max_bytes < 1
        ):
            raise ValueError("invalid taxonomy provider policy")
        self.provider = provider
        self.http = http
        self.quota = quota
        self.max_bytes = max_bytes

    async def read(
        self, identifiers: Sequence[str], *, max_records: int
    ) -> tuple[TaxonRecord, ...]:
        """Return a whole bounded page or raise before exposing partial results."""
        if max_records < 1 or len(identifiers) > max_records:
            raise ValueError("taxonomy request exceeds admitted record bound")
        if len(set(identifiers)) != len(identifiers) or any(
            not _valid_id(identifier) for identifier in identifiers
        ):
            raise ValueError("invalid taxonomy identifiers")
        records: list[TaxonRecord] = []
        for identifier in identifiers:
            async with self.quota(self.provider):
                records.append(await self._read_one(identifier))
        return tuple(records)

    async def _read_one(self, identifier: str) -> TaxonRecord:
        path = (
            f"taxonomy/taxon/{identifier}/dataset_report"
            if self.provider == "ncbi"
            else f"species/{identifier}"
        )
        try:
            async with (
                create_async_http_client(self.http) as client,
                client.stream("GET", path) as response,
            ):
                response.raise_for_status()
                payload = await _bounded(response.aiter_bytes(), self.max_bytes)
            data = json.loads(payload)
            return _normalize(self.provider, identifier, data)
        except Exception:
            raise TaxonomyProviderError("taxonomy provider response refused") from None


async def _bounded(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    result = bytearray()
    async for chunk in chunks:
        if len(result) + len(chunk) > limit:
            raise ValueError("taxonomy response exceeds admitted byte bound")
        result.extend(chunk)
    return bytes(result)


def _normalize(provider: Provider, identifier: str, value: Any) -> TaxonRecord:
    if provider == "gbif":
        if not isinstance(value, dict) or str(value.get("key")) != identifier:
            raise ValueError("GBIF identity mismatch")
        if (
            not isinstance(value.get("scientificName"), str)
            or not value["scientificName"]
        ):
            raise ValueError("missing GBIF scientific name")
        if value.get("parentKey") is not None and not _valid_id(
            str(value["parentKey"])
        ):
            raise ValueError("invalid GBIF parent")
        return taxon_from_gbif(value)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("reports"), list)
        or len(value["reports"]) != 1
    ):
        raise ValueError("invalid NCBI report")
    item = value["reports"][0]["taxonomy"]
    if str(item["tax_id"]) != identifier:
        raise ValueError("NCBI identity mismatch")
    name = item["current_scientific_name"]["name"]
    if not isinstance(name, str) or not name:
        raise ValueError("missing NCBI scientific name")
    parents = item.get("parents", [])
    if not isinstance(parents, list) or (parents and not _valid_id(str(parents[-1]))):
        raise ValueError("invalid NCBI ancestry")
    return taxon_from_ncbi(
        {
            "tax_id": identifier,
            "scientific_name": name,
            "rank": item.get("rank"),
            "parent_tax_id": parents[-1] if parents else None,
        }
    )
