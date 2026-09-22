"""The ``skill`` artifact kind: ``skill://<name>/SKILL.md`` resources."""

from __future__ import annotations

from agent_connector_sdk.artifacts.annotations import _annotations_from_skill
from agent_connector_sdk.artifacts.common import front_matter, mime_type, require_kind
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["SkillArtifactKind"]

_SCHEME = "skill://"
_MAIN_FILE = "/SKILL.md"


def _skill_entry(
    *, uri: str, resource: object, body: str, server: ServerIdentity
) -> CapturedArtifact:
    front = front_matter(body)
    if front is None:
        raise MalformedArtifactError(f"{uri} has no YAML front matter")
    return CapturedArtifact(
        kind=SkillArtifactKind.kind,
        uri=uri,
        name=uri[len(_SCHEME) : -len(_MAIN_FILE)],
        media_type=mime_type(resource, "text/markdown"),
        body=body,
        server=server,
        annotations=_annotations_from_skill(front),
    )


class SkillArtifactKind:
    """Skills served by the skills provider."""

    kind = "skill"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[CapturedArtifact, ...]:
        """One entry per ``SKILL.md`` resource; bodies are read in the same session."""
        entries: list[CapturedArtifact] = []
        for resource in await session.list_resources():
            uri = str(getattr(resource, "uri", ""))
            if not (uri.startswith(_SCHEME) and uri.endswith(_MAIN_FILE)):
                continue
            body = await session.read_resource(uri)
            entries.append(
                _skill_entry(uri=uri, resource=resource, body=body, server=server)
            )
        return tuple(entries)

    def validate(self, entry: CapturedArtifact) -> None:
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
