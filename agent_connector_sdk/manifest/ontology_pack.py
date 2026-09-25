"""Project an SDK connector manifest into EG's typed ontology pack compiler."""

from __future__ import annotations

import re

from epistemic_graph.ontology_pack import compile_ontology_pack

from .model import ConnectorManifest


def _humanize(name: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return words[:1].upper() + words[1:] if words else words


def compile_manifest_ontology(manifest: ConnectorManifest) -> str:
    """Compile declared resources and mappings without SDK-owned RDF syntax."""
    classes: list[dict[str, str | None]] = []
    object_properties: list[dict[str, str | None]] = []
    datatype_properties: dict[str, dict[str, str]] = {}
    for resource in manifest.resources:
        mapping = manifest.schema_mappings.get(resource.name)
        classes.append(
            {
                "local": resource.name,
                "label": resource.label or _humanize(resource.name),
                "parent": mapping.ontology_class if mapping else None,
            }
        )
        if mapping:
            for field, datatype in mapping.fields.items():
                existing = datatype_properties.get(field)
                if existing and existing["range"] != datatype:
                    raise ValueError("conflicting ontology datatypes for one field")
                datatype_properties[field] = {
                    "local": field,
                    "label": _humanize(field),
                    "range": datatype,
                }
        for relation in resource.relations:
            object_properties.append(
                {
                    "local": relation.name,
                    "label": relation.label or _humanize(relation.name),
                    "domain": resource.name,
                    "range": relation.target,
                }
            )
    return compile_ontology_pack(
        source=manifest.resolved_ontology_source,
        classes=classes,
        object_properties=object_properties,
        datatype_properties=list(datatype_properties.values()),
    )


__all__ = ["compile_manifest_ontology"]
