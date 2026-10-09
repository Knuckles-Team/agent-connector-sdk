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

import json
import os
import re
from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "a2a"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug[:80] or "agent"


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _scalar(value: Any) -> str | None:
    """Normalise a possibly-nested value to a scalar string (or None)."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("organization")
            or value.get("id")
            or value.get("value")
        )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tags(value: Any) -> list[str]:
    """Coerce a skill's tags field into a clean list of strings."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple | set):
        return []
    out: list[str] = []
    for item in value:
        text = _scalar(item)
        if text:
            out.append(text)
    return out


def _cards_from_payload(data: Any) -> list[dict[str, Any]]:
    """Normalise a parsed JSON payload into a list of card dicts."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    inner = data.get("cards")
    if isinstance(inner, list):
        return [item for item in inner if isinstance(item, dict)]
    return [data]


def _load_json(path: str) -> list[dict[str, Any]]:
    """Read+json.load a card file, returning a list of card dicts (tolerant)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    return _cards_from_payload(data)


def _collect_cards(config: Any) -> list[dict[str, Any]]:
    """Resolve ``config`` into a flat list of AgentCard dicts.

    Accepts a dict carrying ``cards`` (list of card dicts and/or path
    strings), a single path string, or a list of paths/card dicts.
    """
    raw: Any
    if isinstance(config, str):
        raw = [config]
    elif isinstance(config, list | tuple):
        raw = list(config)
    else:
        raw = _get(config, "cards", []) or []
        if isinstance(raw, str | dict):
            raw = [raw]

    cards: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            cards.append(item)
        elif isinstance(item, str) and os.path.exists(item):
            cards.extend(_load_json(item))
    return cards


def _card_entity(card: dict[str, Any]) -> tuple[str, str, Entity] | None:
    """Build the ``A2AAgentCard`` entity for one card; ``None`` if unnamed."""
    name = _scalar(_get(card, "name"))
    if not name:
        return None
    card_slug = _slug(name)
    card_id = f"a2a:{card_slug}"
    url = _scalar(_get(card, "url")) or _scalar(_get(card, "endpoint"))
    entity = Entity(
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
    return card_id, card_slug, entity


def _card_skill_items(
    card_id: str, card_slug: str, card: Any
) -> tuple[list[Entity], list[Relationship]]:
    """Build the skill entities and ``EXPOSES_SKILL`` relationships for a card."""
    skills = _get(card, "skills") or []
    if isinstance(skills, dict):
        skills = list(skills.values())
    if not isinstance(skills, list | tuple):
        skills = []

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for skill in skills:
        skill_name = _scalar(_get(skill, "name")) or _scalar(_get(skill, "id"))
        if not skill_name:
            continue
        skill_id = f"skill:a2a:{card_slug}:{_slug(skill_name)}"
        entities.append(
            Entity(
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
        )
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
        built = _card_entity(card)
        if built is None:
            continue
        card_id, card_slug, card_entity_obj = built
        entities.append(card_entity_obj)

        skill_entities, skill_relationships = _card_skill_items(
            card_id, card_slug, card
        )
        entities.extend(skill_entities)
        relationships.extend(skill_relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="A2A agent cards (external agents) -> KG",
)
