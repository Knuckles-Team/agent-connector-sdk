"""Default data-resource declarations derived from a connector's tools.

SCION-CONNECTOR-CONTROL-R074. A read-only list or get tool whose output schema
describes records yields one :class:`ResourceDescriptor`: the fields come from
the response schema, the pagination form from the parameters, the access method
from the tool name and its required arguments, and the identity from the field
names. Ontology terms are matched by name against the connector's own classes
and properties. A match is ``proposed``, never approved. A name that matches
nothing stays ``unmapped``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from scion_sdk.artifacts.resource_descriptor import (
    FieldBinding,
    ResourceDescriptor,
)

__all__ = ["OntologyTerms", "derive_descriptors", "scan_ontology"]

_VERBS = frozenset({"list", "get", "search", "find", "fetch", "read", "query"})
_CURSOR = frozenset(
    {
        "cursor", "next_cursor", "page_token", "next_page_token", "after",
        "starting_after", "continuation_token", "next_url", "next_link", "next",
    }
)  # fmt: skip
_OFFSET = frozenset({"offset", "skip", "start", "start_index"})
_PAGE = frozenset({"page", "page_number", "page_num", "pageno"})
_WRAPPER_KEYS = ("items", "results", "data", "records", "entries", "nodes", "values")
_SCALARS = frozenset({"string", "integer", "number", "boolean"})
_KEY_FIELDS = ("id", "uuid", "guid", "key", "node_id", "name", "slug", "number")
_PREFIX = re.compile(r"@prefix\s+(\w*):\s*<([^>]*)>\s*\.")
_TERM = re.compile(
    r"^(?P<s>[\w:<>/#.\-]+)\s+a\s+(?P<t>(?:owl|rdfs|rdf):\w+)", re.MULTILINE
)
_CLASS_TYPES = frozenset({"owl:Class", "rdfs:Class"})
_PROPERTY_TYPES = frozenset(
    {"owl:DatatypeProperty", "owl:ObjectProperty", "rdf:Property"}
)


@dataclass(frozen=True)
class OntologyTerms:
    """Class and property IRIs of a connector ontology, keyed by normalized name."""

    classes: dict[str, str]
    properties: dict[str, str]

    @property
    def class_iris(self) -> frozenset[str]:
        """Every declared class IRI."""
        return frozenset(self.classes.values())


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _expand(subject: str, prefixes: dict[str, str]) -> tuple[str, str] | None:
    if subject.startswith("<") and subject.endswith(">"):
        iri = subject[1:-1]
    else:
        prefix, separator, local = subject.partition(":")
        if not separator or prefix not in prefixes:
            return None
        iri = prefixes[prefix] + local
    return iri, re.split(r"[#/]", iri)[-1]


def scan_ontology(turtle_documents: Iterable[str]) -> OntologyTerms:
    """Read declared classes and properties out of Turtle text."""
    classes: dict[str, str] = {}
    properties: dict[str, str] = {}
    for text in turtle_documents:
        prefixes = dict(_PREFIX.findall(text))
        for match in _TERM.finditer(text):
            term = _expand(match.group("s"), prefixes)
            if term is None:
                continue
            iri, local = term
            kind = match.group("t")
            if kind in _CLASS_TYPES:
                classes[_normal(local)] = iri
            elif kind in _PROPERTY_TYPES:
                properties[_normal(local)] = iri
    return OntologyTerms(classes=classes, properties=properties)


def _resolve(schema: Any, root: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str) and depth < 6:
        node: Any = root
        for part in ref.removeprefix("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return _resolve(node, root, depth + 1)
    return schema


def _record_schema(output: Any) -> tuple[dict[str, Any], bool] | None:
    """The record schema and whether the tool returns a collection of them."""
    root = output if isinstance(output, dict) else {}
    schema = _resolve(root, root)
    props = schema.get("properties")
    if schema.get("x-fastmcp-wrap-result") and isinstance(props, dict):
        schema = _resolve(props.get("result"), root)
    if schema.get("type") == "array":
        record = _resolve(schema.get("items"), root)
        return (record, True) if record.get("properties") else None
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None
    wrapped = _wrapped_collection(props, root)
    if wrapped is not None:
        return wrapped, True
    return (schema, False) if props else None


def _wrapped_collection(props: dict[str, Any], root: dict[str, Any]) -> Any:
    arrays = {
        key: _resolve(_resolve(value, root).get("items"), root)
        for key, value in props.items()
        if _resolve(value, root).get("type") == "array"
    }
    arrays = {k: v for k, v in arrays.items() if v.get("properties")}
    for key in _WRAPPER_KEYS:
        if key in arrays:
            return arrays[key]
    return next(iter(arrays.values())) if len(arrays) == 1 else None


def _field_type(prop: dict[str, Any]) -> str | None:
    kind = prop.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    return kind if kind in _SCALARS else None


def _fields(record: dict[str, Any], root: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for name, prop in record.get("properties", {}).items():
        resolved = _resolve(prop, root)
        kind = _field_type(resolved) or _anyof_type(resolved, root)
        if kind:
            result.append((name, kind))
    return result


def _anyof_type(prop: dict[str, Any], root: dict[str, Any]) -> str | None:
    for option in prop.get("anyOf", ()):
        kind = _field_type(_resolve(option, root))
        if kind:
            return kind
    return None


def _detect_pagination(
    params: dict[str, Any], output_props: Iterable[str]
) -> tuple[str, str | None]:
    names = set(params)
    for mode, known in (("cursor", _CURSOR), ("offset", _OFFSET), ("page", _PAGE)):
        hit = sorted(names & known)
        if hit:
            return mode, hit[0]
    emitted = sorted(set(output_props) & _CURSOR)
    return ("cursor", emitted[0]) if emitted else ("none", None)


def _key_field(names: list[str], resource: str) -> str | None:
    singular = _singular(resource)
    for candidate in ("id", f"{singular}_id", *_KEY_FIELDS[1:]):
        if candidate in names:
            return candidate
    return next((n for n in names if n.endswith("_id")), None)


def _propose(
    fields: list[tuple[str, str]], terms: OntologyTerms, class_iri: str | None
) -> tuple[FieldBinding, ...]:
    bindings = []
    for name, kind in fields:
        prop = terms.properties.get(_normal(name)) if class_iri else None
        bindings.append(
            FieldBinding(
                name=name,
                type=kind,
                ontology_property=prop,
                mapping_status="proposed" if prop else "unmapped",
            )
        )
    return tuple(bindings)


def _propose_class(resource: str, terms: OntologyTerms) -> str | None:
    words = resource.split("_")
    singular = _normal("".join([*words[:-1], _singular(words[-1])]))
    if singular in terms.classes:
        return terms.classes[singular]
    tails = sorted(
        (n for n in terms.classes if singular.endswith(n) and len(n) > 3),
        key=len,
        reverse=True,
    )
    return terms.classes[tails[0]] if tails else None


def _resource_name(tool_name: str) -> str | None:
    tokens = tool_name.lower().split("_")
    for index, token in enumerate(tokens):
        if token in _VERBS and index + 1 < len(tokens):
            return "_".join(t for t in tokens[index + 1 :] if t != "all")
    return None


def _is_read_only(tool: Any) -> bool:
    annotations = getattr(tool, "annotations", None)
    if _hint(annotations, "destructive"):
        return False
    return _hint(annotations, "read_only") is True


def _hint(annotations: Any, name: str) -> Any:
    """An MCP tool annotation under its v2 name, or the v1 camelCase name."""
    if hasattr(annotations, f"{name}_hint"):
        return getattr(annotations, f"{name}_hint")
    head, _, tail = name.partition("_")
    return getattr(annotations, f"{head}{tail.title()}Hint", None)


def _describe(
    connector: str, tool: Any, terms: OntologyTerms
) -> tuple[ResourceDescriptor, bool] | None:
    resource = _resource_name(str(tool.name))
    shape = _record_schema(getattr(tool, "output_schema", None))
    if not resource or shape is None:
        return None
    record, is_collection = shape
    root = getattr(tool, "output_schema", None) or {}
    fields = _fields(record, root)
    key = _key_field([n for n, _ in fields], resource)
    if key is None:
        return None
    params = (getattr(tool, "parameters", None) or {}).get("properties", {})
    required = (getattr(tool, "parameters", None) or {}).get("required", [])
    pagination, param = _detect_pagination(params, record.get("properties", {}))
    class_iri = _propose_class(resource, terms)
    return (
        ResourceDescriptor(
            name=resource,
            uri=f"data://{connector}/{resource}",
            ontology_class=class_iri,
            mapping_status="proposed" if class_iri else "unmapped",
            operation=str(tool.name),
            key_field=key,
            pagination=pagination if is_collection else "none",
            pagination_param=param if is_collection else None,
            origin="derived",
            fields=_propose(fields, terms, class_iri),
            arguments={name: "{" + name + "}" for name in required},
        ),
        is_collection,
    )


def derive_descriptors(
    connector: str, tools: Iterable[Any], terms: OntologyTerms
) -> list[ResourceDescriptor]:
    """One default descriptor per readable record type among ``tools``.

    A list tool is the access method of its resource. A get tool of the same
    resource is kept as ``get_operation``; a get tool alone stands in when the
    resource has no list tool.
    """
    collections: dict[str, ResourceDescriptor] = {}
    singles: dict[str, ResourceDescriptor] = {}
    for tool in sorted(tools, key=lambda t: str(t.name)):
        described = _describe(connector, tool, terms) if _is_read_only(tool) else None
        if described is None:
            continue
        descriptor, is_collection = described
        group = collections if is_collection else singles
        group.setdefault(_singular(descriptor.name), descriptor)
    result = dict(collections)
    for key, single in singles.items():
        owner = collections.get(key)
        if owner is None:
            result[key] = single
        else:
            result[key] = _with_get(owner, single.operation)
    return list(result.values())


def _with_get(owner: ResourceDescriptor, operation: str) -> ResourceDescriptor:
    from dataclasses import replace

    return replace(owner, get_operation=operation)
