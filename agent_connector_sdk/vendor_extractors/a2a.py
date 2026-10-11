"""A2A (Agent-to-Agent) agent-card vendor extractor (SDK-SOURCE-INGEST-R006.22).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.a2a`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`: maps
externally-defined A2A AgentCards into ``A2AAgentCard`` entities, each
declared skill into a ``Skill`` entity linked back via an ``EXPOSES_SKILL``
relationship.

AgentCards are injected via ``config["cards"]`` (a list of standard A2A
agent-card dicts) or referenced as a path / list of paths to JSON card files,
read tolerantly with ``json.load``. Standard card keys handled (all
optional): ``name``, ``description``, ``url``/``endpoint``, ``version``,
``provider``, ``skills`` (list of ``{id|name, description, tags}``). This
module performs no network calls itself.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors._records import _get
from agent_connector_sdk.vendor_extractors.a2a_helpers import (
    _collect_cards,
    _scalar,
    _slug,
    _tags,
)
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "a2a"


def _card_entity(card: dict[str, Any], name: str, card_id: str) -> Entity:
    url = _scalar(_get(card, "url")) or _scalar(_get(card, "endpoint"))
    return Entity(
        id=card_id,
        node_type="A2AAgentCard",
        properties={
            key: value
            for key, value in (
                ("name", name),
                ("description", _scalar(_get(card, "description"))),
                ("url", url),
                ("version", _scalar(_get(card, "version"))),
                ("provider", _scalar(_get(card, "provider"))),
            )
            if value is not None
        },
    )


def _skill_list(card: dict[str, Any]) -> list[Any] | tuple[Any, ...]:
    skills = _get(card, "skills") or []
    if isinstance(skills, dict):
        skills = list(skills.values())
    if not isinstance(skills, list | tuple):
        return []
    return skills


def _skill_entity(skill: Any, skill_id: str) -> Entity:
    return Entity(
        id=skill_id,
        node_type="Skill",
        properties={
            key: value
            for key, value in (
                ("description", _scalar(_get(skill, "description"))),
                ("tags", _tags(_get(skill, "tags"))),
            )
            if value
        },
    )


def _card_skills(
    card: dict[str, Any], card_id: str, card_slug: str
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for skill in _skill_list(card):
        skill_name = _scalar(_get(skill, "name")) or _scalar(_get(skill, "id"))
        if not skill_name:
            continue
        skill_id = f"skill:a2a:{card_slug}:{_slug(skill_name)}"
        entities.append(_skill_entity(skill, skill_id))
        relationships.append(
            Relationship(
                source=card_id,
                target=skill_id,
                relationship="EXPOSES_SKILL",
            )
        )
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    """Extract A2A agent cards into a uniform ``ChangeSet``.

    Each card becomes an ``A2AAgentCard`` entity; each declared skill becomes
    a ``Skill`` entity linked back via ``EXPOSES_SKILL``.
    """
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for card in _collect_cards(config):
        name = _scalar(_get(card, "name"))
        if not name:
            continue
        card_slug = _slug(name)
        card_id = f"a2a:{card_slug}"
        entities.append(_card_entity(card, name, card_id))
        skill_entities, skill_rels = _card_skills(card, card_id, card_slug)
        entities.extend(skill_entities)
        relationships.extend(skill_rels)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="A2A agent cards (external agents) -> KG",
)
