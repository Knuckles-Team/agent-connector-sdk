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


def _dig(record: Any, *path: str) -> Any:
    """Walk a dotted path of dict keys; ``None`` on any missing/non-dict step."""
    current = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _coalesce(record: Any, *paths: str) -> Any:
    for path in paths:
        value = _dig(record, *path.split("."))
        if value is not None:
            return value
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


def _extract_hashtags(record: dict[str, Any]) -> list[str]:
    objects = _coalesce(record, "entities.hashtags", "legacy.entities.hashtags") or []
    return sorted(
        {
            str(item.get("tag") or item.get("text") or "").strip().lower()
            for item in objects
            if isinstance(item, dict)
        }
        - {""}
    )


def _extract_mentions(record: dict[str, Any]) -> list[str]:
    objects = (
        _coalesce(record, "entities.user_mentions", "legacy.entities.user_mentions")
        or []
    )
    return sorted(
        {
            str(item.get("screen_name") or item.get("username") or "").strip().lower()
            for item in objects
            if isinstance(item, dict)
        }
        - {""}
    )


def _extract_urls(
    record: dict[str, Any], exclude_url_hosts: tuple[str, ...]
) -> list[str]:
    objects = _coalesce(record, "entities.urls", "legacy.entities.urls") or []
    urls: list[str] = []
    seen: set[str] = set()
    for item in objects:
        if not isinstance(item, dict):
            continue
        link = str(item.get("expanded_url") or item.get("url") or "").strip()
        if not link or link in seen:
            continue
        host = _domain(link) or ""
        if any(host == ex or host.endswith(f".{ex}") for ex in exclude_url_hosts):
            continue
        seen.add(link)
        urls.append(link)
    return urls


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

    hashtags = _extract_hashtags(record)
    mentions = _extract_mentions(record)
    urls = _extract_urls(record, tuple(exclude_url_hosts))
    tools = _resolve_known_tools(urls)

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    def _stamped(**properties: Any) -> dict[str, Any]:
        return {**properties, "extraction_stage": "deterministic", "confidence": 1.0}

    for tag in hashtags:
        node_id = f"hashtag:{tag}"
        entities.append(
            Entity(id=node_id, node_type="Hashtag", properties=_stamped(name=tag))
        )
        relationships.append(
            Relationship(
                source=document_id, target=node_id, relationship="taggedWithHashtag"
            )
        )

    for handle in mentions:
        node_id = f"mention:{handle}"
        entities.append(
            Entity(id=node_id, node_type="Mention", properties=_stamped(name=handle))
        )
        relationships.append(
            Relationship(
                source=document_id, target=node_id, relationship="mentionsHandle"
            )
        )

    for tool in tools:
        node_id = f"tool:{tool.lower().replace(' ', '-')}"
        entities.append(
            Entity(id=node_id, node_type="Tool", properties=_stamped(name=tool))
        )
        relationships.append(
            Relationship(
                source=document_id, target=node_id, relationship="referencesTool"
            )
        )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Deterministic social/text entities (hashtags/mentions/tools) -> KG",
)
