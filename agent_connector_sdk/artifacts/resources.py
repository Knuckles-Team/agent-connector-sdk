"""The ``resource`` artifact kind: ontologies, shapes, manifest, profiles, A2A cards.

Resource URI schemes map to record kinds through :data:`RESOURCE_RECORD_KINDS`;
an unknown scheme is rejected, never guessed.
"""

from __future__ import annotations

import yaml
from pydantic import ValidationError

from agent_connector_sdk.artifacts.common import json_object, mime_type, require_kind
from agent_connector_sdk.contracts import ArtifactEntry, PackRecord, ServerIdentity
from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["RESOURCE_RECORD_KINDS", "ResourceArtifactKind"]

#: Resource URI scheme to imported record kind.
RESOURCE_RECORD_KINDS: dict[str, str] = {
    "ontology": "Ontology",
    "shapes": "ShapesGraph",
    "manifest": "ConnectorManifest",
    "model-profile": "ModelProfile",
    "a2a-card": "A2AAgentCard",
}


def _scheme(uri: str) -> str:
    scheme, separator, _ = uri.partition("://")
    return scheme if separator else ""


def _validate_body(entry: ArtifactEntry, scheme: str) -> None:
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
    ) -> tuple[ArtifactEntry, ...]:
        """One entry per non-skill resource; bodies are read in the same session."""
        entries: list[ArtifactEntry] = []
        for resource in await session.list_resources():
            uri = str(getattr(resource, "uri", ""))
            if _scheme(uri) == "skill":
                continue
            entries.append(
                ArtifactEntry(
                    kind=self.kind,
                    uri=uri,
                    name=str(getattr(resource, "name", "") or uri),
                    media_type=mime_type(resource, "text/plain"),
                    body=await session.read_resource(uri),
                    server=server,
                )
            )
        return tuple(entries)

    def validate(self, entry: ArtifactEntry) -> None:
        """Known scheme, non-empty body, and a body that parses for its kind."""
        require_kind(entry, self.kind)
        scheme = _scheme(entry.uri)
        if scheme not in RESOURCE_RECORD_KINDS or not entry.body.strip():
            raise MalformedArtifactError(
                f"{entry.uri} has an unknown scheme or empty body"
            )
        _validate_body(entry, scheme)

    def to_record(self, entry: ArtifactEntry) -> PackRecord:
        """A record whose kind is chosen by the URI scheme."""
        self.validate(entry)
        return PackRecord(
            record_kind=RESOURCE_RECORD_KINDS[_scheme(entry.uri)],
            uri=entry.uri,
            name=entry.name,
            entry_digest=entry.digest,
            attributes={"media_type": entry.media_type},
        )
