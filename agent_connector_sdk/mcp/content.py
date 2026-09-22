"""Serve a connector's declarative content as native MCP primitives.

RF-ADR-009 section 2.1: skills, prompts, ontologies, SHACL shapes and the
connector manifest reach epistemic-graph through the MCP primitives the server
already serves. Registered from the connector package layout:

==================================  ==============================================
Package path                        Served as
==================================  ==============================================
``skills/<name>/SKILL.md``          ``skill://<name>/SKILL.md`` (skills provider)
``prompts/<name>.json``             MCP prompt ``<name>`` (``prompts/list``)
``ontology/<file>.ttl``             ``ontology://<connector>/<file>.ttl``
``ontology/shapes/<file>.ttl``      ``shapes://<connector>/<file>.ttl``
``connector_manifest.yml``          ``manifest://connector``
==================================  ==============================================

Replaces ``_register_skill_providers`` and ``_register_prompt_providers`` in
``agent_utilities.mcp.server_factory``, which resolved providers through AU's
install state and served prompts as ``prompt://`` resources rather than MCP
prompts. A malformed content file is an error, not a skipped warning: serving
less than the package declares is how provisioning drifts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp.prompts import Prompt
from fastmcp.resources import FileResource
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from pydantic import AnyUrl

__all__ = [
    "MANIFEST_RESOURCE_URI",
    "ConnectorContent",
    "ContentError",
    "ContentRegistration",
    "register_connector_content",
]

MANIFEST_RESOURCE_URI = "manifest://connector"


class ContentError(ValueError):
    """A connector content file is malformed or missing."""


@dataclass(frozen=True)
class ConnectorContent:
    """Where a connector's content lives.

    Args:
        connector: The connector package name used in resource URIs.
        package_root: The package directory holding ``skills/``, ``prompts/``
            and ``ontology/``.
        package_version: The publisher version recorded on ConnectorPack import.
        manifest_path: The ``connector_manifest.yml`` to serve, if packaged.
    """

    connector: str
    package_root: Path
    package_version: str
    manifest_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.connector.strip() or not self.package_version.strip():
            raise ValueError("connector and package_version are required")


@dataclass(frozen=True)
class ContentRegistration:
    """Counts of what was registered."""

    skills: int
    prompts: int
    resources: int


def _prompt_directive(path: Path) -> tuple[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContentError(f"prompt {path.name} is not readable JSON") from exc
    instructions = document.get("instructions") if isinstance(document, dict) else None
    directive = (
        instructions.get("core_directive") if isinstance(instructions, dict) else None
    )
    if not isinstance(directive, str) or not directive.strip():
        raise ContentError(f"prompt {path.name} has no instructions.core_directive")
    return directive, str(document.get("description") or "")


def _register_prompt(mcp: Any, path: Path) -> None:
    text, description = _prompt_directive(path)

    def render() -> str:
        return text

    mcp.add_prompt(
        Prompt.from_function(render, name=path.stem, description=description)
    )


def _register_skills(mcp: Any, skills_root: Path) -> int:
    count = sum(1 for _ in skills_root.glob("*/SKILL.md"))
    if count:
        mcp.add_provider(SkillsDirectoryProvider(skills_root))
    return count


def _file_resource(uri: str, path: Path, mime_type: str) -> FileResource:
    return FileResource(
        uri=AnyUrl(uri), path=path.resolve(), name=uri, mime_type=mime_type
    )


def _content_resources(content: ConnectorContent) -> list[FileResource]:
    ontology = content.package_root / "ontology"
    resources = [
        _file_resource(
            f"{scheme}://{content.connector}/{path.name}", path, "text/turtle"
        )
        for scheme, directory in (
            ("ontology", ontology),
            ("shapes", ontology / "shapes"),
        )
        for path in sorted(directory.glob("*.ttl"))
    ]
    if content.manifest_path is None:
        return resources
    if not content.manifest_path.is_file():
        raise ContentError("declared connector manifest does not exist")
    resources.append(
        _file_resource(MANIFEST_RESOURCE_URI, content.manifest_path, "text/yaml")
    )
    return resources


def register_connector_content(
    mcp: Any, content: ConnectorContent
) -> ContentRegistration:
    """Register the connector's skills, prompts and content resources on ``mcp``.

    Raises:
        ContentError: a prompt is malformed, or a declared manifest is missing.
    """
    skill_count = _register_skills(mcp, content.package_root / "skills")
    prompt_paths = sorted(
        path
        for path in (content.package_root / "prompts").glob("*.json")
        if not path.name.startswith("_")
    )
    for path in prompt_paths:
        _register_prompt(mcp, path)
    resources = _content_resources(content)
    for resource in resources:
        mcp.add_resource(resource)
    return ContentRegistration(
        skills=skill_count, prompts=len(prompt_paths), resources=len(resources)
    )
