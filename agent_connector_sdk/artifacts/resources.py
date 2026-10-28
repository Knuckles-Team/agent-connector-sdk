"""The ``resource`` artifact kind: ontologies, shapes, profiles, A2A cards and MCP Apps.

Only known generated ConnectorPack resource schemes and the standard MCP Apps
``ui://`` extension are accepted; an unknown scheme is rejected, never guessed.
"""

from __future__ import annotations

import re

from agent_connector_sdk.artifacts.annotations import _annotations_from_mcp
from agent_connector_sdk.artifacts.common import json_object, mime_type, require_kind
from agent_connector_sdk.artifacts.resource_descriptor import RESOURCES_URI
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["ResourceArtifactKind"]

_RESOURCE_SCHEMES = frozenset(
    {"ontology", "shapes", "model-profile", "a2a-card", "data"}
)
_MCP_APP_URI = re.compile(r"^ui://[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_MCP_APP_MEDIA_TYPES = frozenset({"text/html", "text/html;profile=mcp-app"})


def _scheme(uri: str) -> str:
    scheme, separator, _ = uri.partition("://")
    return scheme if separator else ""


def _validate_body(entry: CapturedArtifact, scheme: str) -> None:
    if entry.uri == RESOURCES_URI:
        json_object(entry)
    if scheme in {"a2a-card", "model-profile", "data"}:
        json_object(entry)


def _validate_mcp_app(entry: CapturedArtifact) -> None:
    """Validate the standard MCP Apps resource extension.

    ``ui://`` is a typed extension of the MCP resource primitive, rather than
    a new artifact kind.  The URI is bounded to the extension's resource
    namespace and the body must be HTML served with one of the two wire forms
    used by the MCP Apps implementations: the standard profile MIME type and
    the existing connector-compatible ``text/html`` form.  Server identity is
    retained as independent capture provenance; the URI authority is not
    treated as a second server-name field.
    """
    if not isinstance(entry.uri, str) or not _MCP_APP_URI.fullmatch(entry.uri):
        raise MalformedArtifactError(f"{entry.uri} has an invalid MCP App URI")
    if (
        not isinstance(entry.media_type, str)
        or entry.media_type.strip().lower() not in _MCP_APP_MEDIA_TYPES
    ):
        raise MalformedArtifactError(
            f"{entry.uri} has an unsupported MCP App media type"
        )
    if not isinstance(entry.server, ServerIdentity):
        raise MalformedArtifactError(f"{entry.uri} has invalid server provenance")
    if (
        not isinstance(entry.server.name, str)
        or not isinstance(entry.server.version, str)
        or not entry.server.name.strip()
        or not entry.server.version.strip()
    ):
        raise MalformedArtifactError(f"{entry.uri} has incomplete server provenance")


class ResourceArtifactKind:
    """Content resources other than skills."""

    kind = "resource"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[CapturedArtifact, ...]:
        """Read packaged resources, excluding skills and native server status."""
        entries: list[CapturedArtifact] = []
        for resource in await session.list_resources():
            uri = str(getattr(resource, "uri", ""))
            if _scheme(uri) == "skill" or uri == "connector://status":
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
        if not isinstance(entry.uri, str):
            raise MalformedArtifactError(f"{entry.uri} has an unknown scheme")
        scheme = _scheme(entry.uri)
        if (
            (
                scheme not in _RESOURCE_SCHEMES
                and scheme != "ui"
                and entry.uri != RESOURCES_URI
            )
            or not isinstance(entry.body, str)
            or not entry.body.strip()
        ):
            raise MalformedArtifactError(
                f"{entry.uri} has an unknown scheme or empty body"
            )
        if scheme == "ui":
            _validate_mcp_app(entry)
        else:
            _validate_body(entry, scheme)
