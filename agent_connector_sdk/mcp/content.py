"""Serve a connector's declarative content as native MCP primitives.

RF-ADR-009 section 2.1: skills, prompts, ontologies, SHACL shapes and the
data-source declaration reach epistemic-graph through the MCP primitives the server
already serves. Registered from the connector package layout:

==================================  ==============================================
Package path                        Served as
==================================  ==============================================
``skills/<name>/SKILL.md``          ``skill://<name>/SKILL.md`` (skills provider)
``prompts/<name>.json``             MCP prompt ``<name>`` (``prompts/list``)
``ontology/<file>.ttl``             ``ontology://<connector>/<file>.ttl``
``ontology/shapes/<file>.ttl``      ``shapes://<connector>/<file>.ttl``
(tool ``meta`` via ``source_meta``)   ``connector://resources``
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
from agent_connector_sdk.mcp.prompt_pack_meta import ContentError, _prompt_pack_metadata

__all__ = [
    "ConnectorContent",
    "ContentError",
    "ContentRegistration",
    "ontology_resources",
    "register_connector_content",
    "register_ontology_resources",
]


@dataclass(frozen=True)
class ConnectorContent:
    """Where a connector's content lives.

    Args:
        connector: The connector package name used in resource URIs.
        package_root: The package directory holding ``skills/``, ``prompts/``
            and ``ontology/``.
        package_version: The publisher version recorded on ConnectorPack import.
    """

    connector: str
    package_root: Path
    package_version: str

    def __post_init__(self) -> None:
        if not self.connector.strip() or not self.package_version.strip():
            raise ValueError("connector and package_version are required")

    @classmethod
    def for_package(
        cls,
        package: str,
        package_root: Path,
        package_version: str,
    ) -> ConnectorContent:
        """Build the content of ``package`` under its declared fleet name.

        The connector name comes from
        :func:`agent_connector_sdk.connector_identity.connector_name`; a connector passes
        no name literal.
        """
        from agent_connector_sdk.connector_identity import connector_name

        return cls(
            connector=connector_name(package),
            package_root=package_root,
            package_version=package_version,
        )


@dataclass(frozen=True)
class ContentRegistration:
    """Counts of what was registered."""

    skills: int
    prompts: int
    resources: int
    data_resources: int = 0


#: Reverse-DNS ``_meta`` key carrying a prompt's role, topic, version and target.
PROMPT_META_KEY = "team.knuckles/prompt"


def _prompt_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContentError(f"prompt {path.name} is not readable JSON") from exc
    if not isinstance(document, dict):
        raise ContentError(f"prompt {path.name} has no instructions.core_directive")
    return document


def _composed_text(path: Path, document: dict[str, Any]) -> str:
    instructions = document.get("instructions")
    directive = (
        instructions.get("core_directive") if isinstance(instructions, dict) else None
    )
    if not isinstance(directive, str) or not directive.strip():
        raise ContentError(f"prompt {path.name} has no instructions.core_directive")
    return directive


def _prompt_directive(path: Path) -> tuple[str, str]:
    document = _prompt_document(path)
    return _composed_text(path, document), str(document.get("description") or "")


#: ``metadata`` keys already carried under their own meta name.
_META_FOLDED = frozenset({"topic", "tone", "style", "useCase", "use_case"})


def _text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _prompt_meta(document: dict[str, Any]) -> dict[str, Any]:
    """Role, goal, topic, tone, style, version, use case and system-prompt target.

    These become the ``team.knuckles/prompt`` entry of ``prompts/list`` ``_meta``.
    """
    raw_metadata = document.get("metadata")
    raw_identity = document.get("identity")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    identity: dict[str, Any] = raw_identity if isinstance(raw_identity, dict) else {}
    values = {
        "role": identity.get("role") or document.get("role"),
        "goal": identity.get("goal") or document.get("goal"),
        "topic": metadata.get("topic") or document.get("topic"),
        "tone": metadata.get("tone") or document.get("tone"),
        "style": metadata.get("style") or document.get("style"),
        "version": document.get("prompt_version"),
        "systemPromptFor": document.get("systemPromptFor")
        or document.get("serves")
        or document.get("ontology_class"),
        "useCase": _text(
            document.get("useCase"), metadata.get("useCase"), document.get("use_case")
        ),
    }
    declared = {
        key: value
        for key, value in metadata.items()
        if key not in _META_FOLDED and isinstance(value, (str, int, float, bool))
    }
    return {PROMPT_META_KEY: {**declared, **{k: v for k, v in values.items() if v}}}


def _prompt_title(document: dict[str, Any]) -> str | None:
    identity = document.get("identity")
    return _text(
        document.get("title"),
        identity.get("role") if isinstance(identity, dict) else None,
    )


def _prompt_tags(document: dict[str, Any]) -> set[str]:
    """The prompt's declared ``tags`` plus ``prompt`` and, for a system prompt, ``system``."""
    declared = document.get("tags")
    tags = (
        {t.strip() for t in declared if isinstance(t, str) and t.strip()}
        if isinstance(declared, list)
        else set()
    )
    tags.add("prompt")
    if _prompt_meta(document)[PROMPT_META_KEY].get("systemPromptFor"):
        tags.add("system")
    return tags


def _register_prompt(mcp: Any, path: Path) -> None:
    document = _prompt_document(path)
    text = _composed_text(path, document)

    def render() -> str:
        return text

    mcp.add_prompt(
        Prompt.from_function(
            render,
            name=path.stem,
            title=_prompt_title(document),
            description=str(document.get("description") or ""),
            tags=_prompt_tags(document),
            meta=_prompt_pack_metadata(document, _prompt_meta(document)),
        )
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
    return ontology_resources(content.connector, content.package_root / "ontology")


def _ontology_texts(content: ConnectorContent) -> list[str]:
    directory = content.package_root / "ontology"
    return [p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.ttl"))]


def _register_resource_descriptors(mcp: Any, content: ConnectorContent) -> int:
    """Serve ``connector://resources`` with the derived data-resource descriptors."""
    from agent_connector_sdk.ingest.live_declaration import (
        load_sources_module,
        register_live_declaration,
    )
    from agent_connector_sdk.mcp.tool_surface import registered_tools

    declared = load_sources_module(content.package_root)
    if not _ontology_texts(content) and not declared:
        return 0

    def descriptors() -> list[dict[str, Any]]:
        terms = scan_ontology(_ontology_texts(content))
        derived = derive_descriptors(
            content.connector, registered_tools(mcp).values(), terms
        )
        return [d.to_json() for d in derived]

    register_live_declaration(
        mcp,
        content.connector,
        descriptors,
        declared=declared,
    )
    return 1


def register_connector_content(
    mcp: Any, content: ConnectorContent
) -> ContentRegistration:
    """Register the connector's skills, prompts and content resources on ``mcp``.

    Raises:
        ContentError: a prompt is malformed.
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
