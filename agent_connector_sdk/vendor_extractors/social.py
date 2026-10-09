"""Deterministic social/text entity vendor extractor (SDK-SOURCE-INGEST-R006.28).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.social`` onto this
SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`: mines a
source platform's own structured entity metadata (hashtags, @-mentions,
outbound URLs) directly from an already-fetched record, producing
``Hashtag``/``Mention``/``Tool`` entities linked back to the source document
by ``taggedWithHashtag``/``mentionsHandle``/``referencesTool`` relationships
-- no LLM call, no extra network round trip, no cost.

``config`` carries ``record`` (the already-fetched platform record, schema-
defensive over the common v2-style top-level ``entities.*`` and v1.1-style
``legacy.entities.*`` shapes), ``document_id`` (the entity id relationships
originate from), and an optional ``exclude_url_hosts`` tuple of link-
shortener/self-referential hosts to filter out. This module performs no
network calls itself.

Scope note: the agent-utilities source reads these two shapes through a
shared, generic dotted-path digger
(``agent_utilities.knowledge_graph.etl.transforms``) this SDK does not depend
on; this port reads the same two shapes with direct dict access instead.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "social"

# Curated domain -> canonical tool/product name. An exact host match, or a
# registered-suffix match for subdomains (e.g. ``xyz.github.io``).
KNOWN_TOOL_DOMAINS: dict[str, str] = {
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "stackoverflow.com": "Stack Overflow",
    "npmjs.com": "npm",
    "pypi.org": "PyPI",
    "huggingface.co": "Hugging Face",
    "arxiv.org": "arXiv",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "notion.so": "Notion",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "discord.com": "Discord",
    "slack.com": "Slack",
    "reddit.com": "Reddit",
}


def _get(config: Any, key: str, default: Any = None) -> Any:
    return (
        config.get(key, default)
        if isinstance(config, dict)
        else getattr(config, key, default)
    )


def _coalesce(record: Any, *paths: str) -> Any:
    """First non-``None`` value found by walking each dotted path of dict keys."""
    for path in paths:
        current: Any = record
        for key in path.split("."):
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current is not None:
            return current
    return None


def _domain(url: str) -> str | None:
    """Best-effort hostname extraction, ``www.``-stripped."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def _resolve_known_tools(urls: list[str]) -> list[str]:
    """Resolve a document's outbound links to known tool/product names."""
    seen: set[str] = set()
    tools: list[str] = []
    for url in urls:
        host = _domain(url)
        if not host:
            continue
        name = KNOWN_TOOL_DOMAINS.get(host)
        if name is None and "." in host:
            _, _, parent = host.partition(".")
            name = KNOWN_TOOL_DOMAINS.get(parent)
        if name and name not in seen:
            seen.add(name)
            tools.append(name)
    return tools


def _extract_tagged(
    record: dict[str, Any], paths: tuple[str, str], *, primary: str, fallback: str
) -> list[str]:
    """Deduplicated, lowercased values from a v2/legacy ``entities.*`` list."""
    objects = _coalesce(record, *paths) or []
    return sorted(
        {
            str(item.get(primary) or item.get(fallback) or "").strip().lower()
            for item in objects
            if isinstance(item, dict)
        }
        - {""}
    )


def _normalized_url(
    item: Any, seen: set[str], exclude_url_hosts: tuple[str, ...]
) -> str | None:
    """A usable, not-yet-seen, not-excluded link from one ``entities.urls`` item."""
    if not isinstance(item, dict):
        return None
    link = str(item.get("expanded_url") or item.get("url") or "").strip()
    if not link or link in seen:
        return None
    host = _domain(link) or ""
    if any(host == ex or host.endswith(f".{ex}") for ex in exclude_url_hosts):
        return None
    return link


def _extract_urls(
    record: dict[str, Any], exclude_url_hosts: tuple[str, ...]
) -> list[str]:
    objects = _coalesce(record, "entities.urls", "legacy.entities.urls") or []
    urls: list[str] = []
    seen: set[str] = set()
    for item in objects:
        link = _normalized_url(item, seen, exclude_url_hosts)
        if link is None:
            continue
        seen.add(link)
        urls.append(link)
    return urls


def _stamped(**properties: Any) -> dict[str, Any]:
    return {**properties, "extraction_stage": "deterministic", "confidence": 1.0}


def _group_entities_and_relationships(
    document_id: str,
    items: list[str],
    *,
    prefix: str,
    node_type: str,
    relationship: str,
    slug: bool,
) -> tuple[list[Entity], list[Relationship]]:
    """Entities + relationships for one group (hashtags/mentions/tools)."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for item in items:
        key = item.lower().replace(" ", "-") if slug else item
        node_id = f"{prefix}:{key}"
        entities.append(
            Entity(id=node_id, node_type=node_type, properties=_stamped(name=item))
        )
        relationships.append(
            Relationship(source=document_id, target=node_id, relationship=relationship)
        )
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    """Mine a record's own structured ``entities`` metadata into a ``ChangeSet``.

    Hashtags/mentions/tools become entities, stamped
    ``extraction_stage="deterministic"`` so this free-first pass stays
    distinguishable in provenance from any later LLM-derived enrichment of
    the same document, with relationships back to ``document_id``.
    """
    record = _get(config, "record")
    document_id = _get(config, "document_id")
    exclude_url_hosts = _get(config, "exclude_url_hosts", ()) or ()
    if not isinstance(record, dict) or not document_id:
        return ChangeSet()

    hashtags = _extract_tagged(
        record,
        ("entities.hashtags", "legacy.entities.hashtags"),
        primary="tag",
        fallback="text",
    )
    mentions = _extract_tagged(
        record,
        ("entities.user_mentions", "legacy.entities.user_mentions"),
        primary="screen_name",
        fallback="username",
    )
    urls = _extract_urls(record, tuple(exclude_url_hosts))
    tools = _resolve_known_tools(urls)

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    groups = (
        (hashtags, "hashtag", "Hashtag", "taggedWithHashtag", False),
        (mentions, "mention", "Mention", "mentionsHandle", False),
        (tools, "tool", "Tool", "referencesTool", True),
    )
    for items, prefix, node_type, relationship, slug in groups:
        group_entities, group_relationships = _group_entities_and_relationships(
            document_id,
            items,
            prefix=prefix,
            node_type=node_type,
            relationship=relationship,
            slug=slug,
        )
        entities.extend(group_entities)
        relationships.extend(group_relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Deterministic social/text entities (hashtags/mentions/tools) -> KG",
)
