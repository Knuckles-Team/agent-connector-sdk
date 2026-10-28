"""Occurrence graph context admits exact source taxa and locations."""

from datetime import UTC, datetime

import pytest

from agent_connector_sdk.earth_observations.occurrence_context import (
    OccurrenceContext,
    _occurrence_entities,
)
from agent_connector_sdk.earth_observations.records import (
    OrganismObservation,
    Place,
    Region,
)
from agent_connector_sdk.taxonomy.records import TaxonRecord


def _row():
    now = datetime(2025, 1, 1, tzinfo=UTC)
    return OrganismObservation(
        tenant_id="tenant",
        source_id="occurrences",
        provider="gbif",
        source_event_id="1",
        event_time_utc=now,
        observed_at_utc=now,
        license_tag="CC-BY",
        source_digest="digest",
        taxon_id="GBIF:7",
        scientific_name="Taxon",
        place_id="gbif:occurrence:1:location",
        latitude=45,
        longitude=-92,
        basis_of_record="HUMAN_OBSERVATION",
    )


def _context():
    place = Place(
        place_id="gbif:occurrence:1:location",
        name="Site",
        region_id="region",
        latitude=45,
        longitude=-92,
    )
    region = Region(region_id="region", name="Region", kind="operator")
    taxon = TaxonRecord(scientific_name="Taxon", term_curie="GBIF:7", gbif_taxon_id="7")
    return OccurrenceContext(
        taxa={"GBIF:7": taxon},
        places={place.place_id: place},
        regions={region.region_id: region},
    )


def test_occurrence_graph_entities_use_admitted_taxon_and_place():
    records, edges = _occurrence_entities([_row()], _context())
    assert {record["node_type"] for record in records} == {
        "OrganismObservation",
        "Taxon",
        "Place",
        "Region",
    }
    assert {edge["relationship"] for edge in edges} == {
        "observedTaxon",
        "occurredAt",
        "locatedIn",
    }


def test_occurrence_refuses_unapproved_identity_or_coordinates():
    context = _context()
    for row in (
        _row().model_copy(update={"taxon_id": "GBIF:8"}),
        _row().model_copy(update={"latitude": 46}),
    ):
        with pytest.raises(ValueError):
            _occurrence_entities([row], context)
