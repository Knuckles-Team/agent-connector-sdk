"""Taxon record identity and the TaxonShape cardinality rules it mirrors."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_connector_sdk.taxonomy.records import (
    TaxonRecord,
    taxon_from_gbif,
    taxon_from_ncbi,
)

_NCBI_HUMAN = {
    "tax_id": "9606",
    "scientific_name": "Homo sapiens",
    "rank": "species",
    "parent_tax_id": "9605",
}

_GBIF_HUMAN = {
    "key": 5219243,
    "scientificName": "Homo sapiens Linnaeus, 1758",
    "rank": "SPECIES",
    "parentKey": 2436436,
}


def test_ncbi_taxon_carries_one_term_curie_and_one_scientific_name() -> None:
    taxon = taxon_from_ncbi(_NCBI_HUMAN)

    assert taxon.term_curie == "NCBITaxon:9606"
    assert taxon.scientific_name == "Homo sapiens"
    assert taxon.ncbi_taxon_id == "9606"
    assert taxon.gbif_taxon_id is None
    assert taxon.parent_term_curie == "NCBITaxon:9605"


def test_gbif_taxon_carries_its_own_term_curie_and_parent() -> None:
    taxon = taxon_from_gbif(_GBIF_HUMAN)

    assert taxon.term_curie == "GBIF:5219243"
    assert taxon.gbif_taxon_id == "5219243"
    assert taxon.ncbi_taxon_id is None
    assert taxon.parent_term_curie == "GBIF:2436436"


def test_a_taxon_without_a_parent_leaves_parent_term_curie_unset() -> None:
    root = taxon_from_ncbi({**_NCBI_HUMAN, "parent_tax_id": None})
    assert root.parent_term_curie is None


def test_ncbi_taxon_id_must_be_decimal() -> None:
    with pytest.raises(ValidationError, match="decimal"):
        TaxonRecord(
            scientific_name="Homo sapiens",
            term_curie="NCBITaxon:9606",
            ncbi_taxon_id="not-a-number",
        )


def test_scientific_name_and_term_curie_are_required() -> None:
    with pytest.raises(ValidationError):
        TaxonRecord(scientific_name="", term_curie="NCBITaxon:9606")
