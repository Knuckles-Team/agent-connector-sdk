"""Accumulator for schema entities and relationships during introspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scion_sdk.ingest.model import Entity, Relationship


@dataclass
class _SchemaSink:
    """Bundles the growing node/edge lists during schema introspection."""

    nodes: list[Entity] = field(default_factory=list)
    edges: list[Relationship] = field(default_factory=list)

    def add_member(
        self,
        parent_id: str,
        member_id: str,
        node_type: str,
        properties: dict[str, Any],
        relationship: str,
    ) -> None:
        """Add one entity and the edge that attaches it to ``parent_id``."""
        self.nodes.append(
            Entity(id=member_id, node_type=node_type, properties=properties)
        )
        self.edges.append(
            Relationship(source=parent_id, target=member_id, relationship=relationship)
        )
