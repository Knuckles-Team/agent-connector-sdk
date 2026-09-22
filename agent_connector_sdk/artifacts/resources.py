"""The ``resource`` artifact kind: ontologies, shapes, manifest, profiles, A2A cards.

Only generated ConnectorPack resource schemes are accepted; an unknown scheme
is rejected, never guessed.
"""

from __future__ import annotations

import yaml
from pydantic import ValidationError

from agent_connector_sdk.artifacts.annotations import _annotations_from_mcp
from agent_connector_sdk.artifacts.common import json_object, mime_type, require_kind
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["ResourceArtifactKind"]

_RESOURCE_SCHEMES = frozenset(
    {"ontology", "shapes", "manifest", "model-profile", "a2a-card"}
)


def _scheme(uri: str) -> str:
    scheme, separator, _ = uri.partition("://")
    return scheme if separator else ""


def _validate_body(entry: CapturedArtifact, scheme: str) -> None:
    if scheme == "manifest":
        try:
            ConnectorManifest.model_validate(yaml.safe_load(entry.body))
        except (yaml.YAMLError, ValidationError) as exc:
            raise MalformedArtifactError(
                f"{entry.uri} is not a valid manifest"
            ) from exc
    if scheme in {"a2a-card", "model-profile"}:
        json_object(entry)


class ResourceArtifactKind:
    """Content resources other than skills."""

    kind = "resource"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[CapturedArtifact, ...]:
        """One entry per non-skill resource; bodies are read in the same session."""
        entries: list[CapturedArtifact] = []
        for resource in await session.list_resources():
            uri = str(getattr(resource, "uri", ""))
            if _scheme(uri) == "skill":
                continue
            entries.append(
                CapturedArtifact(
                    kind=self.kind,
                    uri=uri,
                    name=str(getattr(resource, "name", "") or uri),
                    media_type=mime_type(resource, "text/plain"),
                    body=await session.read_resource(uri),
                    server=server,
                    annotations=_annotations_from_mcp(resource),
                )
            )
        return tuple(entries)

    def validate(self, entry: CapturedArtifact) -> None:
        """Known scheme, non-empty body, and a body that parses for its kind."""
        require_kind(entry, self.kind)
        scheme = _scheme(entry.uri)
        if scheme not in _RESOURCE_SCHEMES or not entry.body.strip():
            raise MalformedArtifactError(
                f"{entry.uri} has an unknown scheme or empty body"
            )
        _validate_body(entry, scheme)
