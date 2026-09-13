"""The ``skill`` artifact kind: ``skill://<name>/SKILL.md`` resources."""

from __future__ import annotations

from agent_connector_sdk.artifacts.common import front_matter, mime_type, require_kind
from agent_connector_sdk.contracts import ArtifactEntry, PackRecord, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["SkillArtifactKind"]

_SCHEME = "skill://"
_MAIN_FILE = "/SKILL.md"


class SkillArtifactKind:
    """Skills served by the skills provider."""

    kind = "skill"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[ArtifactEntry, ...]:
        """One entry per ``SKILL.md`` resource; bodies are read in the same session."""
        entries: list[ArtifactEntry] = []
        for resource in await session.list_resources():
            uri = str(getattr(resource, "uri", ""))
            if not (uri.startswith(_SCHEME) and uri.endswith(_MAIN_FILE)):
                continue
            entries.append(
                ArtifactEntry(
                    kind=self.kind,
                    uri=uri,
                    name=uri[len(_SCHEME) : -len(_MAIN_FILE)],
                    media_type=mime_type(resource, "text/markdown"),
                    body=await session.read_resource(uri),
                    server=server,
                )
            )
        return tuple(entries)

    def validate(self, entry: ArtifactEntry) -> None:
        """YAML front matter whose ``name`` matches, with a description."""
        require_kind(entry, self.kind)
        front = front_matter(entry.body)
        if front is None:
            raise MalformedArtifactError(f"{entry.uri} has no YAML front matter")
        if (
            front.get("name") != entry.name
            or not str(front.get("description") or "").strip()
        ):
            raise MalformedArtifactError(f"{entry.uri} front matter is incomplete")

    def to_record(self, entry: ArtifactEntry) -> PackRecord:
        """A ``Skill`` record."""
        self.validate(entry)
        front = front_matter(entry.body) or {}
        return PackRecord(
            record_kind="Skill",
            uri=entry.uri,
            name=entry.name,
            entry_digest=entry.digest,
            attributes={"description": str(front.get("description", "")).strip()},
        )
