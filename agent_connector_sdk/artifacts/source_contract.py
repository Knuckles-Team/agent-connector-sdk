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
        terms: list[tuple[str, str | int]] = [
            ("classIri", descriptor.ontology_class),
            ("sourceId", f"{connector}/{descriptor.name}"),
            ("entity", descriptor.name),
            ("keyField", descriptor.key_field),
            ("accessKind", descriptor.access_kind),
            ("operation", descriptor.operation),
            ("pagination", descriptor.pagination),
        ]
        optional = (
            ("recordsPath", descriptor.records_path),
            ("paginationParam", descriptor.pagination_param),
            ("nextCursorPath", descriptor.next_cursor_path),
            ("pageSize", descriptor.page_size),
            ("pageSizeParam", descriptor.page_size_param),
            ("completion", descriptor.completion),
            (
                "startPage",
                descriptor.start_page if descriptor.pagination == "page" else None,
            ),
            (
                "startOffset",
                descriptor.start_offset if descriptor.pagination == "offset" else None,
            ),
            ("authRef", descriptor.credential_ref),
        )
        terms.extend((name, value_) for name, value_ in optional if value_ is not None)
        lines.append(f"<{identity}> a ac:AccessContract ;")
        for index, (name, value_) in enumerate(terms):
            terminator = " ." if index == len(terms) - 1 else " ;"
            lines.append(
                f"    ac:{name} {json.dumps(value_, ensure_ascii=False)}{terminator}"
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
            or contract.records_path != descriptor.records_path
            or contract.pagination_param != descriptor.pagination_param
            or contract.next_cursor_path != descriptor.next_cursor_path
            or contract.page_size != descriptor.page_size
            or contract.page_size_param != descriptor.page_size_param
            or contract.completion != descriptor.completion
            or contract.start_page
            != (descriptor.start_page if descriptor.pagination == "page" else None)
            or contract.start_offset
            != (descriptor.start_offset if descriptor.pagination == "offset" else None)
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
