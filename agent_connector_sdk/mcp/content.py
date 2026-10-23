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

from agent_connector_sdk.artifacts.resource_derivation import (
    derive_descriptors,
    scan_ontology,
)
from agent_connector_sdk.artifacts.resource_descriptor import (
    RESOURCES_URI,
    ResourceDeclarationError,
    check_declarations,
    load_declarations,
    merge_declarations,
    render_resources_document,
)

__all__ = [
    "MANIFEST_RESOURCE_URI",
    "ConnectorContent",
    "ContentError",
    "ContentRegistration",
    "ontology_resources",
    "register_connector_content",
    "register_ontology_resources",
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
        declared = _manifest_connector(self.manifest_path)
        if declared is not None and declared != self.connector:
            raise ContentError(
                f"content connector {self.connector!r} disagrees with the "
                f"manifest connector {declared!r}"
            )

    @classmethod
    def for_package(
        cls,
        package: str,
        package_root: Path,
        package_version: str,
        manifest_path: Path | None = None,
    ) -> ConnectorContent:
        """Build the content of ``package`` under its declared fleet name.

        The connector name comes from
        :func:`agent_connector_sdk.connector_identity.connector_name`; a connector passes
        no name literal. ``manifest_path`` defaults to
        ``package_root/connector_manifest.yml`` when that file exists.
        """
        from agent_connector_sdk.connector_identity import connector_name

        if manifest_path is None and (package_root / MANIFEST_FILE).is_file():
            manifest_path = package_root / MANIFEST_FILE
        return cls(
            connector=connector_name(package),
            package_root=package_root,
            package_version=package_version,
            manifest_path=manifest_path,
        )


MANIFEST_FILE = "connector_manifest.yml"


def _manifest_connector(path: Path | None) -> str | None:
    """The ``connector`` a packaged manifest declares, if it is readable."""
    if path is None or not path.is_file():
        return None
    import yaml

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ContentError(f"manifest {path.name} is not readable YAML") from exc
    connector = document.get("connector") if isinstance(document, dict) else None
    return connector if isinstance(connector, str) else None


@dataclass(frozen=True)
class ContentRegistration:
    """Counts of what was registered."""

    skills: int
    prompts: int
    resources: int
    data_resources: int = 0


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


def ontology_resources(connector: str, ontology_dir: Path) -> list[FileResource]:
    """Build the ``ontology://`` and ``shapes://`` resources of one ontology directory.

    ``ontology_dir/*.ttl`` become ``ontology://<connector>/<file>.ttl`` and
    ``ontology_dir/shapes/*.ttl`` become ``shapes://<connector>/<file>.ttl``.
    A missing directory yields no resources.
    """
    return [
        _file_resource(f"{scheme}://{connector}/{path.name}", path, "text/turtle")
        for scheme, directory in (
            ("ontology", ontology_dir),
            ("shapes", ontology_dir / "shapes"),
        )
        for path in sorted(directory.glob("*.ttl"))
    ]


def register_ontology_resources(mcp: Any, connector: str, ontology_dir: Path) -> int:
    """Register one ontology directory's resources on ``mcp``; return the count.

    The host-side half of :func:`register_connector_content` for servers that
    already serve skills and prompts through their own providers.
    """
    resources = ontology_resources(connector, ontology_dir)
    for resource in resources:
        mcp.add_resource(resource)
    return len(resources)


def _content_resources(content: ConnectorContent) -> list[FileResource]:
    resources = ontology_resources(content.connector, content.package_root / "ontology")
    if content.manifest_path is None:
        return resources
    if not content.manifest_path.is_file():
        raise ContentError("declared connector manifest does not exist")
    resources.append(
        _file_resource(MANIFEST_RESOURCE_URI, content.manifest_path, "text/yaml")
    )
    return resources


def _ontology_texts(content: ConnectorContent) -> list[str]:
    directory = content.package_root / "ontology"
    return [p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.ttl"))]


def _resource_descriptors(mcp: Any, content: ConnectorContent) -> str:
    """The ``manifest://connector/resources`` body, derived when it is read.

    Tools register after the factory runs, so the defaults are derived from
    the tools registered at read time and overlaid by the connector's own
    ``data_resources.json``.
    """
    from agent_connector_sdk.mcp.tool_surface import registered_tools

    terms = scan_ontology(_ontology_texts(content))
    derived = derive_descriptors(
        content.connector, registered_tools(mcp).values(), terms
    )
    descriptors = merge_declarations(
        content.connector,
        derived,
        load_declarations(content.package_root),
        terms.class_iris or None,
    )
    return render_resources_document(content.connector, descriptors)


def _register_resource_descriptors(mcp: Any, content: ConnectorContent) -> int:
    """Serve the data-resource declarations when the package has an ontology."""
    declared = load_declarations(content.package_root)
    texts = _ontology_texts(content)
    if not texts and not declared:
        return 0
    try:
        classes = scan_ontology(texts).class_iris
        check_declarations(declared, classes or None)
    except ResourceDeclarationError as exc:
        raise ContentError(str(exc)) from exc

    def read() -> str:
        return _resource_descriptors(mcp, content)

    mcp.resource(
        RESOURCES_URI,
        name=RESOURCES_URI,
        mime_type="application/json",
        description="Data resources this connector exposes for virtual access.",
    )(read)
    return 1


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
    descriptors = _register_resource_descriptors(mcp, content)
    return ContentRegistration(
        skills=skill_count,
        prompts=len(prompt_paths),
        resources=len(resources),
        data_resources=descriptors,
    )
