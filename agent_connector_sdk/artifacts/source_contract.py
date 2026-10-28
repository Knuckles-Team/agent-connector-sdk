"""Render captured data-resource descriptors as access contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from urllib.parse import quote

from agent_connector_sdk.access_contract import AC, parse_access_contracts
from agent_connector_sdk.artifacts.resource_descriptor import ResourceDescriptor


def render_source_contract(
    connector: str, values: Sequence[Mapping[str, object]]
) -> str:
    """Return deterministic flat Turtle that the existing access parser reads.

    The URI identifies a contract candidate, not an approval. All reads still
    require the engine's owner-issued approval and caller's fleet grant.
    """
    lines = [f"@prefix ac: <{AC}> ."]
    expected = []
    for value in sorted(values, key=lambda item: str(item.get("uri", ""))):
        descriptor = ResourceDescriptor.from_json(value)
        if not descriptor.ontology_class:
            raise ValueError("RESOURCE_UNMAPPED: descriptor has no ontology class")
        if (
            not re.fullmatch(r"[A-Za-z0-9._~-]+", connector)
            or not re.fullmatch(r"[A-Za-z0-9._~-]+", descriptor.name)
            or descriptor.uri != f"data://{connector}/{descriptor.name}"
        ):
            raise ValueError(
                "RESOURCE_URI_INVALID: descriptor identity is not canonical"
            )
        identity = f"{descriptor.uri}#access"
        terms = (
            ("classIri", descriptor.ontology_class),
            ("sourceId", f"{connector}/{descriptor.name}"),
            ("entity", descriptor.name),
            ("keyField", descriptor.key_field),
            ("accessKind", descriptor.access_kind),
            ("operation", descriptor.operation),
            ("pagination", descriptor.pagination),
        )
        lines.append(f"<{identity}> a ac:AccessContract ;")
        for index, (name, value_) in enumerate(terms):
            terminator = (
                " ."
                if index == len(terms) - 1 and not descriptor.credential_ref
                else " ;"
            )
            lines.append(
                f"    ac:{name} {json.dumps(value_, ensure_ascii=False)}{terminator}"
            )
        if descriptor.credential_ref:
            lines.append(
                f"    ac:authRef {json.dumps(descriptor.credential_ref, ensure_ascii=False)} ."
            )
        for field in sorted(descriptor.fields, key=lambda item: item.name):
            if field.ontology_property:
                binding = f"{identity}/field/{quote(field.name, safe='')}"
                lines.append(
                    f"<{binding}> a ac:PropertyBinding ; ac:contract <{identity}> ; "
                    f"ac:property {json.dumps(field.ontology_property, ensure_ascii=False)} ; "
                    f"ac:field {json.dumps(field.name, ensure_ascii=False)} ."
                )
        expected.append(descriptor)
    rendered = "\n".join(lines) + "\n"
    parsed = parse_access_contracts(rendered)
    if len(parsed) != len(expected):
        raise ValueError("RESOURCE_CONTRACT_INVALID: duplicate contract identity")
    for contract, descriptor in zip(parsed, expected, strict=True):
        if (
            contract.contract_iri != f"{descriptor.uri}#access"
            or contract.source_id != f"{connector}/{descriptor.name}"
            or contract.entity != descriptor.name
            or contract.class_iri != descriptor.ontology_class
            or contract.key_field != descriptor.key_field
            or contract.access_kind != descriptor.access_kind
            or contract.operation != descriptor.operation
            or contract.pagination != descriptor.pagination
            or contract.auth_ref != descriptor.credential_ref
            or contract.predicates
            != tuple(
                sorted(
                    (field.ontology_property, field.name)
                    for field in descriptor.fields
                    if field.ontology_property
                )
            )
        ):
            raise ValueError(
                "RESOURCE_CONTRACT_INVALID: declaration did not round trip"
            )
    return rendered
