"""Connector data sources declared in code and served live over MCP.

SDK-CONNECTOR-CONTROL-R075: the connector's MCP server is the only place its
metadata is read from. A read tool carries its data-source declaration in its
tool ``meta`` (:func:`source_meta`); the server serves the assembled
declaration as the ``connector://resources`` resource. Tool fingerprints come
from the handshake.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from agent_connector_sdk.artifacts.resource_descriptor import RESOURCES_URI
from agent_connector_sdk.ingest.sources import (
    IngestSourceDeclaration,
    IngestSourceSpec,
)
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping

__all__ = [
    "DECLARATION_SCHEMA_VERSIONS",
    "META_KEY",
    "RESOURCES_URI",
    "SOURCES_MODULE",
    "DeclarationError",
    "build_declaration",
    "expand_field_sets",
    "load_declaration",
    "load_sources_module",
    "register_live_declaration",
    "source_meta",
]

#: The tool ``meta`` key holding a tool's source declarations.
META_KEY = "connector_sources"
#: The generated module a package may ship to declare sources by tool name.
SOURCES_MODULE = "connector_sources"


def source_meta(
    *,
    source_id: str,
    record_type: str,
    id_field: str,
    ontology_class: str | None = None,
    fields: Mapping[str, str] | None = None,
    tool: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    """The ``meta=`` argument that declares a read tool as an ingestible source.

    ``options`` are the other :class:`IngestSourceSpec` fields (records path,
    title/text/cursor fields, paging) and ``preset`` (extra runner extraction
    fields). ``ontology_class`` and ``fields`` map the record type onto the
    connector ontology. Pass ``mcp.tool(..., meta=source_meta(...))``; combine
    several with :func:`merge_meta`-style dict update on ``META_KEY`` lists.
    ``tool`` names the read tool when the declaration lives in a module that
    does not decorate the tool (``<package>.connector_sources.SOURCES``).
    """
    entry: dict[str, Any] = {
        "source_id": source_id,
        "record_type": record_type,
        "id_field": id_field,
        **options,
    }
    if ontology_class is not None or fields:
        entry["mapping"] = {
            "ontology_class": ontology_class,
            "fields": dict(fields or {}),
        }
    IngestSourceSpec.model_validate(
        {**{k: v for k, v in entry.items() if k != "mapping"}, "tools": ("x",)}
    )
    entry.setdefault("preset", {})
    if tool is not None:
        entry["tool"] = tool
    return {META_KEY: [entry]}


def _entries(tool: Any) -> list[dict[str, Any]]:
    meta = getattr(tool, "meta", None) or {}
    value = meta.get(META_KEY) if isinstance(meta, dict) else None
    return [e for e in value or () if isinstance(e, dict)]


#: ``SCHEMA_VERSION`` values the reader accepts. 1 spells each mapping's fields
#: inline; 2 may also name shared ``FIELD_SETS`` (SDK-SOURCE-INGEST-R004.29).
DECLARATION_SCHEMA_VERSIONS = (1, 2)


class DeclarationError(ValueError):
    """A connector's declared sources are missing or malformed."""


def expand_field_sets(
    mapping: Mapping[str, Any], field_sets: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    """Merge the shared field sets a mapping names into its own ``fields``.

    A mapping lists ``field_sets`` by name; its inline ``fields`` win over a
    set. The result has no ``field_sets`` key.

    Raises:
        DeclarationError: a mapping names a set that is not declared.
    """
    merged: dict[str, str] = {}
    for name in mapping.get("field_sets", ()):
        if name not in field_sets:
            raise DeclarationError(f"mapping names unknown field set {name!r}")
        merged.update(field_sets[name])
    merged.update(mapping.get("fields", {}))
    return {
        **{k: v for k, v in mapping.items() if k != "field_sets"},
        "fields": merged,
    }


def _expanded_sources(
    sources: Iterable[Mapping[str, Any]], field_sets: Mapping[str, Mapping[str, str]]
) -> tuple[Mapping[str, Any], ...]:
    out = []
    for item in sources:
        entries = []
        for entry in item.get(META_KEY, ()):
            mapping = entry.get("mapping")
            entries.append(
                {**entry, "mapping": expand_field_sets(mapping, field_sets)}
                if mapping
                else entry
            )
        out.append({**item, META_KEY: entries})
    return tuple(out)


def load_sources_module(package_root: Path | str | None) -> Mapping[str, Any] | None:
    """The package's ``connector_sources`` module attributes, or ``None``.

    The module holds ``SOURCES`` (``source_meta(tool=...)`` results),
    ``SCHEMA_MAPPINGS`` and ``RESOURCES``, so a generator declares sources for
    tools built from client methods without editing a tool function.
    """
    if package_root is None:
        return None
    module = Path(package_root).name
    try:
        loaded = importlib.import_module(f"{module}.{SOURCES_MODULE}")
    except ModuleNotFoundError as exc:
        if exc.name in (module, f"{module}.{SOURCES_MODULE}"):
            return None
        raise
    schema_version = getattr(loaded, "SCHEMA_VERSION", 1)
    if schema_version not in DECLARATION_SCHEMA_VERSIONS:
        raise DeclarationError(
            f"{module}.{SOURCES_MODULE} has SCHEMA_VERSION {schema_version!r}; "
            f"this SDK reads {DECLARATION_SCHEMA_VERSIONS}"
        )
    field_sets = dict(getattr(loaded, "FIELD_SETS", {}))
    return {
        "SOURCES": _expanded_sources(getattr(loaded, "SOURCES", ()), field_sets),
        "SCHEMA_MAPPINGS": {
            key: expand_field_sets(mapping, field_sets)
            for key, mapping in dict(getattr(loaded, "SCHEMA_MAPPINGS", {})).items()
        },
        "RESOURCES": tuple(getattr(loaded, "RESOURCES", ())),
    }


def load_declaration(package: str) -> IngestSourceDeclaration:
    """Build ``package``'s ingest declaration from its ``connector_sources`` data.

    The fleet name comes from the connector's declared identity. Shared
    ``FIELD_SETS`` expand once per mapping. This replaces the ``declaration()``
    helper that every connector carried (SDK-SOURCE-INGEST-R004.29).

    Raises:
        DeclarationError: the package ships no ``connector_sources`` module, or
            declares a duplicate source, an unknown field set or an unsupported
            ``SCHEMA_VERSION``.
    """
    from agent_connector_sdk.connector_identity import connector_name

    top = package.split(".", 1)[0]
    spec = importlib.util.find_spec(top)
    locations = list(spec.submodule_search_locations or []) if spec else []
    declared = load_sources_module(Path(locations[0])) if locations else None
    if declared is None:
        raise DeclarationError(f"{top} ships no {SOURCES_MODULE} module")
    sources: dict[str, IngestSourceSpec] = {}
    mappings: dict[str, SchemaMapping] = {}
    for item in declared["SOURCES"]:
        for entry in item.get(META_KEY, ()):
            body = {k: v for k, v in entry.items() if k not in ("tool", "mapping")}
            spec_ = IngestSourceSpec.model_validate({**body, "tools": (entry["tool"],)})
            if spec_.source_id in sources:
                raise DeclarationError(f"duplicate source_id {spec_.source_id!r}")
            sources[spec_.source_id] = spec_
            if entry.get("mapping"):
                mappings[spec_.record_type] = SchemaMapping.model_validate(
                    entry["mapping"]
                )
    for key, mapping in declared["SCHEMA_MAPPINGS"].items():
        mappings[key] = SchemaMapping.model_validate(mapping)
    return IngestSourceDeclaration(
        connector=connector_name(top),
        sources=tuple(sources.values()),
        schema_mappings=mappings,
        resources=tuple(ResourceSpec.model_validate(r) for r in declared["RESOURCES"]),
    )


def build_declaration(
    connector: str,
    tools: Iterable[Any],
    descriptors: Iterable[dict[str, Any]] = (),
    declared: Mapping[str, Any] | None = None,
) -> IngestSourceDeclaration:
    """Assemble the declaration from the tools' ``meta`` and a sources module.

    Raises:
        ValueError: the sources module names a tool the server does not register.
    """
    tool_list = list(tools)
    names = {str(getattr(t, "name", "")) for t in tool_list}
    pairs: list[tuple[str, dict[str, Any]]] = []
    for tool in sorted(tool_list, key=lambda t: str(getattr(t, "name", ""))):
        pairs += [(tool.name, entry) for entry in _entries(tool)]
    for item in (declared or {}).get("SOURCES", ()):
        for entry in item.get(META_KEY, ()):
            if entry.get("tool") not in names:
                raise ValueError(
                    f"connector_sources declares unknown tool {entry.get('tool')!r}"
                )
            pairs.append((entry["tool"], entry))
    sources: dict[str, IngestSourceSpec] = {}
    mappings: dict[str, SchemaMapping] = {}
    for name, entry in pairs:
        body = {k: v for k, v in entry.items() if k != "tool"}
        mapping = body.pop("mapping", None)
        spec = IngestSourceSpec.model_validate({**body, "tools": (name,)})
        sources[spec.source_id] = spec
        if mapping:
            mappings[spec.record_type] = SchemaMapping.model_validate(mapping)
    for key, mapping in (declared or {}).get("SCHEMA_MAPPINGS", {}).items():
        mappings.setdefault(key, SchemaMapping.model_validate(mapping))
    return IngestSourceDeclaration(
        connector=connector,
        sources=tuple(sources.values()),
        schema_mappings=mappings,
        resources=tuple(
            ResourceSpec.model_validate(r)
            for r in (declared or {}).get("RESOURCES", ())
        ),
        descriptors=tuple(descriptors),
    )


def register_live_declaration(
    mcp: Any,
    connector: str,
    descriptors: Callable[[], list[dict[str, Any]]] | None = None,
    declared: Mapping[str, Any] | None = None,
    surface_summary: Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]]
    | None = None,
) -> None:
    """Serve ``connector://resources``, computed when read.

    The body lists the sources declared on the registered tools, their
    ontology mappings and, when ``descriptors`` is given, the data-resource
    descriptors. ``declared`` is the package's ``connector_sources`` module. A server that already serves the URI keeps its resource.
    """
    from agent_connector_sdk.mcp.tool_surface import registered_tools

    served = getattr(getattr(mcp, "_local_provider", None), "_components", {})
    if any(RESOURCES_URI in str(key) for key in served):
        return

    async def resources() -> str:
        """The data sources and resources this connector declares, as JSON."""
        current_descriptors = descriptors() if descriptors is not None else []
        declaration = build_declaration(
            connector,
            registered_tools(mcp).values(),
            current_descriptors,
            declared,
        )
        if surface_summary is not None:
            declaration = IngestSourceDeclaration.model_validate(
                {
                    **declaration.model_dump(),
                    "surfaces": await surface_summary(current_descriptors),
                }
            )
        return json.dumps(
            declaration.model_dump(mode="json", exclude_unset=True), sort_keys=True
        )

    mcp.resource(
        RESOURCES_URI,
        name="connector-resources",
        mime_type="application/json",
        description="Data sources, ontology mappings and resources of this connector.",
    )(resources)
