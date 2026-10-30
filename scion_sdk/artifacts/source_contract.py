"""Render captured data-resource descriptors as access contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from urllib.parse import quote

from scion_sdk.access_contract import (
    AC,
    AccessContract,
    parse_access_contracts,
)
from scion_sdk.artifacts.resource_descriptor import ResourceDescriptor


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
        expected.append(_render_descriptor(connector, value, lines))
    rendered = "\n".join(lines) + "\n"
    parsed = parse_access_contracts(rendered)
    if len(parsed) != len(expected):
        raise ValueError("RESOURCE_CONTRACT_INVALID: duplicate contract identity")
    for contract, descriptor in zip(parsed, expected, strict=True):
        _verify_round_trip(connector, contract, descriptor)
    return rendered


def _render_descriptor(
    connector: str, value: Mapping[str, object], lines: list[str]
) -> ResourceDescriptor:
    descriptor = ResourceDescriptor.from_json(value)
    class_iri = _validate_identity(connector, descriptor)
    identity = f"{descriptor.uri}#access"
    terms: list[tuple[str, str | int]] = [
        ("classIri", class_iri),
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
    return descriptor


def _validate_identity(connector: str, descriptor: ResourceDescriptor) -> str:
    if not descriptor.ontology_class:
        raise ValueError("RESOURCE_UNMAPPED: descriptor has no ontology class")
    if (
        not re.fullmatch(r"[A-Za-z0-9._~-]+", connector)
        or not re.fullmatch(r"[A-Za-z0-9._~-]+", descriptor.name)
        or descriptor.uri != f"data://{connector}/{descriptor.name}"
    ):
        raise ValueError("RESOURCE_URI_INVALID: descriptor identity is not canonical")
    return descriptor.ontology_class


def _verify_round_trip(
    connector: str, contract: AccessContract, descriptor: ResourceDescriptor
) -> None:
    actual = (
        contract.contract_iri,
        contract.source_id,
        contract.entity,
        contract.class_iri,
        contract.key_field,
        contract.access_kind,
        contract.operation,
        contract.pagination,
        contract.records_path,
        contract.pagination_param,
        contract.next_cursor_path,
        contract.page_size,
        contract.page_size_param,
        contract.completion,
        contract.start_page,
        contract.start_offset,
        contract.auth_ref,
        contract.predicates,
    )
    expected = (
        f"{descriptor.uri}#access",
        f"{connector}/{descriptor.name}",
        descriptor.name,
        descriptor.ontology_class,
        descriptor.key_field,
        descriptor.access_kind,
        descriptor.operation,
        descriptor.pagination,
        descriptor.records_path,
        descriptor.pagination_param,
        descriptor.next_cursor_path,
        descriptor.page_size,
        descriptor.page_size_param,
        descriptor.completion,
        descriptor.start_page if descriptor.pagination == "page" else None,
        descriptor.start_offset if descriptor.pagination == "offset" else None,
        descriptor.credential_ref,
        tuple(
            sorted(
                (field.ontology_property, field.name)
                for field in descriptor.fields
                if field.ontology_property
            )
        ),
    )
    if actual != expected:
        raise ValueError("RESOURCE_CONTRACT_INVALID: declaration did not round trip")
