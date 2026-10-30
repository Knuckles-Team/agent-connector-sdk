"""ArchiMate model vendor extractor (SCION-SOURCE-INGEST-R006.5).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.archimate`` onto this
SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`: elements
become entities typed by their ArchiMate class (``BusinessProcess``,
``ApplicationComponent``, ``Node``, ...) instead of agent-utilities'
``GraphNode``, and relationships become ``Relationship`` records instead of
``EnrichmentEdge``. The client is injected through ``config`` and this module
performs no I/O of its own.
"""

from __future__ import annotations

import re
from typing import Any

from scion_sdk.ingest import ChangeSet, Entity, Relationship
from scion_sdk.vendor_extractors._extract_common import _call_dict_rows, _entity_of
from scion_sdk.vendor_extractors._records import _get
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "archimate"


def _upper_snake(name: str) -> str:
    """``relApplicationToITComponent`` -> ``REL_APPLICATION_TO_IT_COMPONENT``."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.upper()


def _entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for element in _call_dict_rows(client, "list_elements"):
        element_id = element.get("id")
        element_type = element.get("type")
        if not (element_id and element_type):
            continue
        properties = {
            "name": element.get("name"),
            "documentation": element.get("documentation"),
            "externalToolId": str(element_id),
            "domain": CATEGORY,
        }
        entities.append(_entity_of(f"archi:{element_id}", element_type, properties))
    return entities


def _relationships(client: Any) -> list[Relationship]:
    relationships: list[Relationship] = []
    for relationship in _call_dict_rows(client, "list_relationships"):
        source, target = relationship.get("source"), relationship.get("target")
        if not (source and target):
            continue
        relationships.append(
            Relationship(
                source=f"archi:{source}",
                target=f"archi:{target}",
                relationship=_upper_snake(relationship.get("type") or "ASSOCIATION"),
            )
        )
    return relationships


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    return ChangeSet(
        entities=tuple(_entities(client)),
        relationships=tuple(_relationships(client)),
    )


register_vendor_extractor(
    CATEGORY,
    extract,
    description="ArchiMate model elements/relationships -> KG entities",
)
