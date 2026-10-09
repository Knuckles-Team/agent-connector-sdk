"""Normalized ``Taxon`` record and its NCBI/GBIF source mappings.

``SDK-SOURCE-INGEST-R009`` calls for a taxonomy connector that ingests NCBI
Taxonomy and GBIF backbone taxa as ``kg:Taxon`` individuals carrying rank,
parent, scientific name, NCBI and GBIF identifiers, and a term CURIE,
validated against the world_model-v1 ``TaxonShape``
(``epistemic-graph/crates/eg-core/ontology/world_model-v1.shapes.ttl``).
``TaxonRecord`` mirrors that shape's cardinalities at the SDK boundary:
exactly one ``scientific_name`` and one ``term_curie``, at most one
``taxon_rank`` and one ``parent_term_curie``, and an ``ncbi_taxon_id`` that is
digits only when present. Graph-side shape validation, delta-bound
synchronization and the live connector adapter are a follow-up slice.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["TaxonRecord", "taxon_from_gbif", "taxon_from_ncbi"]

_NCBI_TAXON_ID_PATTERN = re.compile(r"^[0-9]+$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaxonRecord(_Frozen):
    """One taxon normalized to the world_model-v1 ``TaxonShape`` cardinalities."""

    scientific_name: str = Field(min_length=1)
    term_curie: str = Field(min_length=1)
    taxon_rank: str | None = None
    parent_term_curie: str | None = None
    ncbi_taxon_id: str | None = None
    gbif_taxon_id: str | None = None

    @model_validator(mode="after")
    def _ncbi_taxon_id_is_decimal(self) -> Self:
        if self.ncbi_taxon_id is not None and not _NCBI_TAXON_ID_PATTERN.match(
            self.ncbi_taxon_id
        ):
            raise ValueError("ncbi_taxon_id must be a decimal NCBI Taxonomy id")
        return self


def taxon_from_ncbi(raw: Mapping[str, Any]) -> TaxonRecord:
    """Normalize one NCBI Taxonomy record (``tax_id``, ``parent_tax_id``, ...)."""
    tax_id = str(raw["tax_id"])
    parent_tax_id = raw.get("parent_tax_id")
    return TaxonRecord(
        scientific_name=str(raw["scientific_name"]),
        term_curie=f"NCBITaxon:{tax_id}",
        taxon_rank=raw.get("rank"),
        parent_term_curie=(
            f"NCBITaxon:{parent_tax_id}" if parent_tax_id is not None else None
        ),
        ncbi_taxon_id=tax_id,
        gbif_taxon_id=None,
    )


def taxon_from_gbif(raw: Mapping[str, Any]) -> TaxonRecord:
    """Normalize one GBIF backbone record (``key``, ``parentKey``, ...)."""
    key = str(raw["key"])
    parent_key = raw.get("parentKey")
    return TaxonRecord(
        scientific_name=str(raw["scientificName"]),
        term_curie=f"GBIF:{key}",
        taxon_rank=raw.get("rank"),
        parent_term_curie=f"GBIF:{parent_key}" if parent_key is not None else None,
        ncbi_taxon_id=None,
        gbif_taxon_id=key,
    )
