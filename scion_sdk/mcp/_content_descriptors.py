"""Data-resource descriptors served as ``connector://resources`` by :mod:`scion_sdk.mcp.content`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scion_sdk.artifacts.resource_derivation import derive_descriptors, scan_ontology
from scion_sdk.artifacts.resource_descriptor import ResourceDescriptor

if TYPE_CHECKING:
    from scion_sdk.mcp.content import ConnectorContent


def _ontology_texts(content: ConnectorContent) -> list[str]:
    directory = content.package_root / "ontology"
    return [p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.ttl"))]


def _merge_descriptor(
    descriptor: ResourceDescriptor, sources: Any, terms: Any
) -> dict[str, Any]:
    from scion_sdk.artifacts.resource_descriptor import (
        ResourceDeclarationError,
    )

    matches = [
        source for source in sources.sources if descriptor.operation in source.tools
    ]
    if len(matches) > 1:
        raise ResourceDeclarationError(
            "DECLARATION_AMBIGUOUS",
            f"{descriptor.operation}: multiple source declarations",
        )
    if matches:
        descriptor = _apply_source(descriptor, matches[0], sources, terms=terms)

    return descriptor.to_json()


def _apply_source(
    descriptor: ResourceDescriptor, source: Any, sources: Any, *, terms: Any
) -> ResourceDescriptor:
    from dataclasses import replace

    mapping = sources.schema_mappings.get(source.record_type)
    class_iri = _source_class(descriptor, source, mapping, terms=terms)
    fields = _mapped_fields(descriptor, mapping)
    descriptor = replace(
        descriptor,
        ontology_class=class_iri,
        mapping_status="declared"
        if mapping and mapping.ontology_class
        else descriptor.mapping_status,
        origin="declared",
        key_field=source.id_field,
        pagination=source.pagination,
        pagination_param={
            "page": source.page_param,
            "cursor": source.cursor_param,
            "offset": source.offset_param,
        }.get(source.pagination),
        records_path=source.records_path or None,
        next_cursor_path=source.next_cursor_path,
        page_size=source.page_size if source.pagination in {"page", "offset"} else None,
        page_size_param=source.page_size_param,
        start_page=source.start_page,
        start_offset=source.start_offset,
        completion=source.pagination_completion
        or ("short_page" if source.pagination == "page" else None),
        fields=tuple(fields.values()),
    )

    return descriptor


def _source_class(descriptor: Any, source: Any, mapping: Any, *, terms: Any) -> Any:
    from scion_sdk.artifacts.resource_descriptor import (
        ResourceDeclarationError,
    )

    class_iri = (
        mapping.ontology_class
        if mapping and mapping.ontology_class
        else descriptor.ontology_class
    )
    if mapping and mapping.ontology_class and class_iri not in terms.class_iris:
        raise ResourceDeclarationError(
            "RESOURCE_UNMAPPED", f"{source.source_id}: {class_iri}"
        )
    return class_iri


def _mapped_fields(descriptor: Any, mapping: Any) -> dict[str, Any]:
    from dataclasses import replace

    from scion_sdk.artifacts.resource_descriptor import FieldBinding

    fields = {field.name: field for field in descriptor.fields}
    if mapping:
        for name, property_iri in mapping.fields.items():
            original = fields.get(name, FieldBinding(name=name))
            fields[name] = replace(
                original,
                ontology_property=property_iri,
                mapping_status="declared",
            )
    return fields


def _register_resource_descriptors(mcp: Any, content: ConnectorContent) -> int:
    """Serve ``connector://resources`` with the derived data-resource descriptors."""
    from scion_sdk.ingest.live_declaration import (
        build_declaration,
        load_sources_module,
        register_live_declaration,
    )
    from scion_sdk.mcp.tool_surface import registered_tools

    declared = load_sources_module(content.package_root)
    if not _ontology_texts(content) and not declared:
        return 0

    def descriptors() -> list[dict[str, Any]]:
        terms = scan_ontology(_ontology_texts(content))
        tools = list(registered_tools(mcp).values())
        derived = derive_descriptors(content.connector, tools, terms)
        sources = build_declaration(content.connector, tools, declared=declared)
        return [_merge_descriptor(descriptor, sources, terms) for descriptor in derived]

    from scion_sdk.mcp.data_resources import (
        _DataResourceProvider,
        _surface_summary,
    )

    mcp.add_provider(_DataResourceProvider(descriptors))
    register_live_declaration(
        mcp,
        content.connector,
        descriptors,
        declared=declared,
        surface_summary=lambda items: _surface_summary(
            mcp, content.package_root, items
        ),
    )
    return 1
