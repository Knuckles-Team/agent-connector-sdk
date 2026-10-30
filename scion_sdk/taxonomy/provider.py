"""Bounded reads of explicitly admitted taxonomy identifiers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal

from scion_sdk.http._bounded_provider import _BoundedProvider, _fetch
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.taxonomy.records import (
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


def _valid_identifier_batch(identifiers: Sequence[str], batch_size: int) -> bool:
    return (
        bool(identifiers)
        and 1 <= batch_size <= 1000
        and len(identifiers) <= 10000
        and len(set(identifiers)) == len(identifiers)
        and all(_valid_id(item) for item in identifiers)
    )


class TaxonomyProviderError(RuntimeError):
    """A provider page could not be obtained or validated."""


class TaxonomyProvider(_BoundedProvider[Provider]):
    """Read admitted IDs under caller-supplied provider and quota policies."""

    def __init__(
        self,
        *,
        provider: Provider,
        http: HttpClientOptions,
        quota: Quota,
        max_bytes: int,
    ) -> None:
        if provider not in ("ncbi", "gbif"):
            raise ValueError("invalid taxonomy provider policy")
        super().__init__(provider=provider, http=http, quota=quota, max_bytes=max_bytes)

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
        try:
            return await self._read_record(identifier)
        except Exception:
            raise TaxonomyProviderError("taxonomy provider response refused") from None

    async def _read_record(self, identifier: str) -> TaxonRecord:
        path = (
            f"taxonomy/taxon/{identifier}/dataset_report"
            if self.provider == "ncbi"
            else f"species/{identifier}"
        )
        payload = await _fetch(self.http, path, self.max_bytes)
        return _normalize(self.provider, identifier, json.loads(payload))


def _normalize(provider: Provider, identifier: str, value: Any) -> TaxonRecord:
    if provider == "gbif":
        return _normalize_gbif(identifier, value)
    return _normalize_ncbi(identifier, value)


def _normalize_gbif(identifier: str, value: Any) -> TaxonRecord:
    if (
        not isinstance(value, dict)
        or str(value.get("key")) != identifier
        or str(value.get("nubKey")) != identifier
    ):
        raise ValueError("GBIF backbone identity mismatch")
    if not isinstance(value.get("scientificName"), str) or not value["scientificName"]:
        raise ValueError("missing GBIF scientific name")
    if value.get("parentKey") is not None and not _valid_id(str(value["parentKey"])):
        raise ValueError("invalid GBIF parent")
    return taxon_from_gbif(value)


def _valid_ancestry(parents: Any) -> bool:
    return isinstance(parents, list) and (not parents or _valid_id(str(parents[-1])))


def _normalize_ncbi(identifier: str, value: Any) -> TaxonRecord:
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
    if not _valid_ancestry(parents):
        raise ValueError("invalid NCBI ancestry")
    return taxon_from_ncbi(
        {
            "tax_id": identifier,
            "scientific_name": name,
            "rank": item.get("rank"),
            "parent_tax_id": parents[-1] if parents else None,
        }
    )
