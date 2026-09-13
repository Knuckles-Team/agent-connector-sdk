"""Helpers shared by the artifact kinds."""

from __future__ import annotations

import json
from typing import Any

import yaml

from agent_connector_sdk.contracts import ArtifactEntry
from agent_connector_sdk.ports.errors import MalformedArtifactError

__all__ = ["canonical_json", "front_matter", "json_object", "mime_type", "require_kind"]


def canonical_json(value: Any) -> str:
    """Sorted-key, whitespace-free JSON: equal content, equal text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def json_object(entry: ArtifactEntry) -> dict[str, Any]:
    """The entry body as a JSON object.

    Raises:
        MalformedArtifactError: the body is not a JSON object.
    """
    try:
        document = json.loads(entry.body)
    except json.JSONDecodeError as exc:
        raise MalformedArtifactError(f"{entry.uri} body is not JSON") from exc
    if not isinstance(document, dict):
        raise MalformedArtifactError(f"{entry.uri} body is not a JSON object")
    return document


def require_kind(entry: ArtifactEntry, kind: str) -> None:
    """Reject an entry of another kind."""
    if entry.kind != kind:
        raise MalformedArtifactError(f"{entry.uri} is a {entry.kind}, not a {kind}")


def mime_type(item: Any, default: str) -> str:
    """A listed resource's MIME type (SDK v2 or v1 attribute name)."""
    value = getattr(item, "mime_type", None) or getattr(item, "mimeType", None)
    return str(value or default)


def front_matter(body: str) -> dict[str, Any] | None:
    """The YAML front matter of a Markdown document, or ``None``."""
    header, separator, _ = body.removeprefix("---\n").partition("\n---")
    if not body.startswith("---\n") or not separator:
        return None
    try:
        document = yaml.safe_load(header)
    except yaml.YAMLError:
        return None
    return document if isinstance(document, dict) else None
