"""Host-admitted taxonomy and locations for occurrence graph ingestion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from agent_connector_sdk.earth_observations.records import (
    OrganismObservation,
    Place,
    Region,
)
from agent_connector_sdk.taxonomy.records import TaxonRecord


@dataclass(frozen=True)
class OccurrenceContext:
    """Approved source-taxon bindings and exact source locations."""

    taxa: Mapping[str, TaxonRecord]
    places: Mapping[str, Place]
    regions: Mapping[str, Region]

    def __post_init__(self) -> None:
        object.__setattr__(self, "taxa", MappingProxyType(dict(self.taxa)))
        object.__setattr__(self, "places", MappingProxyType(dict(self.places)))
        object.__setattr__(self, "regions", MappingProxyType(dict(self.regions)))
        _validate_context(self)


def _validate_context(context: OccurrenceContext) -> None:
    if not context.taxa or not context.places or not context.regions:
        raise ValueError("occurrence context is empty")
    if any(key != place.place_id for key, place in context.places.items()):
        raise ValueError("occurrence place identity mismatch")
    if any(key != region.region_id for key, region in context.regions.items()):
        raise ValueError("occurrence region identity mismatch")
    if any(place.region_id not in context.regions for place in context.places.values()):
        raise ValueError("occurrence place has no admitted region")
    _validate_taxon_identities(context.taxa)


def _validate_taxon_identities(taxa: Mapping[str, TaxonRecord]) -> None:
    by_term: dict[str, TaxonRecord] = {}
    for taxon in taxa.values():
        prior = by_term.setdefault(taxon.term_curie, taxon)
        if prior != taxon:
            raise ValueError("occurrence taxon identity conflicts")


def _context_identity(context: OccurrenceContext) -> list[Any]:
    return [
        [
            (key, value.model_dump(mode="json"))
            for key, value in sorted(context.taxa.items())
        ],
        [
            (key, value.model_dump(mode="json"))
            for key, value in sorted(context.places.items())
        ],
        [
            (key, value.model_dump(mode="json"))
            for key, value in sorted(context.regions.items())
        ],
    ]


def _occurrence_entities(
    rows: Sequence[OrganismObservation], context: OccurrenceContext
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, str]] = []
    for row in rows:
        taxon = context.taxa.get(row.taxon_id)
        place = context.places.get(row.place_id)
        if (
            taxon is None
            or place is None
            or row.scientific_name != taxon.scientific_name
        ):
            raise ValueError("occurrence identity not admitted")
        if row.latitude != place.latitude or row.longitude != place.longitude:
            raise ValueError("occurrence coordinates not admitted")
        region = context.regions[place.region_id]
        observation_id = f"{row.provider}:{row.source_event_id}"
        taxon_id = f"taxon:{taxon.term_curie}"
        place_id = f"place:{place.place_id}"
        region_id = f"region:{region.region_id}"
        records.append(
            dict(
                row.model_dump(mode="json", exclude_none=True),
                id=observation_id,
                node_type="OrganismObservation",
            )
        )
        nodes[taxon_id] = dict(
            taxon.model_dump(mode="json", exclude_none=True),
            id=taxon_id,
            node_type="Taxon",
        )
        nodes[place_id] = dict(
            place.model_dump(mode="json"), id=place_id, node_type="Place"
        )
        nodes[region_id] = dict(
            region.model_dump(mode="json"), id=region_id, node_type="Region"
        )
        relationships.extend(
            [
                {
                    "source": observation_id,
                    "target": taxon_id,
                    "relationship": "observedTaxon",
                },
                {
                    "source": observation_id,
                    "target": place_id,
                    "relationship": "occurredAt",
                },
                {"source": place_id, "target": region_id, "relationship": "locatedIn"},
            ]
        )
    records.extend(nodes[key] for key in sorted(nodes))
    return records, relationships
