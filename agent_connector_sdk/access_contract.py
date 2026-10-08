"""Connector access contracts: how each ontology class is answered live.

A connector ontology declares ``ac:AccessContract`` subjects with the
vocabulary in ``ontology/access_contract.ttl`` (SDK-CONNECTOR-CONTROL-R021).
:func:`parse_access_contracts` reads them into typed :class:`AccessContract`
values. It refuses a missing operation, an unknown access kind, pagination
or pushdown operation, and an ``ac:authRef`` that is not a credential
reference. A literal secret therefore never becomes a contract.

The parser reads the flat Turtle profile: ``@prefix`` lines, prefixed names,
``<IRIs>``, ``a``, string and integer literals, and ``;`` ``,`` ``.``.
Blank nodes and collections are refused.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from importlib import resources

from .credentials.references import SecretReferenceError, parse_secret_reference

__all__ = [
    "AC",
    "ACCESS_KINDS",
    "PAGINATION_MODES",
    "PUSHDOWN_OPS",
    "AccessContract",
    "AccessContractError",
    "access_contract_vocabulary",
    "parse_access_contracts",
]

AC = "https://knuckles-team.github.io/agent-connector-sdk/access#"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
ACCESS_KINDS = frozenset({"mcp_tool", "http_endpoint", "graphql_query", "a2a_skill"})
PAGINATION_MODES = frozenset({"none", "cursor", "offset", "page"})
PUSHDOWN_OPS = frozenset({"filter", "sort", "limit", "project"})
COST_HINTS = frozenset({"low", "medium", "high"})

_TOKEN_RE = re.compile(
    r"(?P<ws>\s+|#[^\n]*)"
    r"|(?P<iri><[^<>\s]*>)"
    r'|(?P<str>"(?:[^"\\\n]|\\.)*")'
    r"|(?P<int>-?\d+)"
    r"|(?P<prefix>@prefix)"
    r"|(?P<pname>[A-Za-z_]?[\w-]*:(?:[\w-](?:[\w.-]*[\w-])?)?)"
    r"|(?P<a>a(?=\s))"
    r"|(?P<punct>[;,.])"
)

Term = str | int
Triple = tuple[str, str, Term]


class AccessContractError(ValueError):
    """A connector ontology declares an invalid access contract."""


@dataclass(frozen=True)
class AccessContract:
    """One ontology class bound to one live source operation.

    ``source_id``, ``entity``, ``class_iri``, ``key_field`` and ``predicates``
    match the agent-utilities ``VirtualMapping`` fields of the same name.
    """

    contract_iri: str
    class_iri: str
    source_id: str
    entity: str
    key_field: str
    access_kind: str
    operation: str
    parameters: tuple[str, ...] = ()
    pagination: str = "none"
    pushdown: frozenset[str] = field(default_factory=frozenset)
    auth_ref: str | None = None
    rate_limit_per_minute: int | None = None
    freshness_seconds: int | None = None
    cost_hint: str = "unknown"
    predicates: tuple[tuple[str, str], ...] = ()

    def virtual_mapping_fields(self) -> dict[str, object]:
        """Return the keyword arguments of an unapproved ``VirtualMapping``."""
        return {
            "mapping_id": self.contract_iri,
            "source_id": self.source_id,
            "entity": self.entity,
            "class_iri": self.class_iri,
            "key_field": self.key_field,
            "predicates": self.predicates,
        }


def access_contract_vocabulary() -> str:
    """Return the packaged access-contract vocabulary as Turtle text."""
    path = resources.files("agent_connector_sdk") / "ontology" / "access_contract.ttl"
    return path.read_text(encoding="utf-8")


def _tokens(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            raise AccessContractError(f"unsupported Turtle at offset {pos}")
        kind = match.lastgroup or ""
        if kind != "ws":
            out.append((kind, match.group()))
        pos = match.end()
    return out


class _Reader:
    def __init__(self, text: str) -> None:
        self.toks = _tokens(text)
        self.pos = 0
        self.prefixes: dict[str, str] = {}
        self.triples: list[Triple] = []

    def next(self) -> tuple[str, str]:
        if self.pos >= len(self.toks):
            raise AccessContractError("unexpected end of Turtle")
        self.pos += 1
        return self.toks[self.pos - 1]

    def expect(self, value: str) -> None:
        if self.next()[1] != value:
            raise AccessContractError(f"expected {value!r}")

    def term(self) -> Term:
        kind, value = self.next()
        if kind == "iri":
            return value[1:-1]
        if kind == "a":
            return _RDF_TYPE
        if kind == "pname":
            prefix, _, local = value.partition(":")
            if prefix not in self.prefixes:
                raise AccessContractError(f"undeclared prefix {prefix!r}")
            return self.prefixes[prefix] + local
        if kind == "str":
            return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if kind == "int":
            return int(value)
        raise AccessContractError(f"unexpected token {value!r}")

    def prefix(self) -> None:
        kind, name = self.next()
        iri = self.next()
        if kind != "pname" or not name.endswith(":") or iri[0] != "iri":
            raise AccessContractError("malformed @prefix")
        self.prefixes[name[:-1]] = iri[1][1:-1]
        self.expect(".")

    def statement(self) -> None:
        subject = str(self.term())
        sep = ";"
        while sep == ";":
            predicate = str(self.term())
            sep = ","
            while sep == ",":
                self.triples.append((subject, predicate, self.term()))
                sep = self.next()[1]
        if sep != ".":
            raise AccessContractError("statement must end with '.'")

    def read(self) -> list[Triple]:
        while self.pos < len(self.toks):
            if self.toks[self.pos][0] == "prefix":
                self.pos += 1
                self.prefix()
            else:
                self.statement()
        return self.triples


def _index(triples: list[Triple]) -> dict[str, dict[str, list[Term]]]:
    graph: dict[str, dict[str, list[Term]]] = defaultdict(lambda: defaultdict(list))
    for subject, predicate, obj in triples:
        graph[subject][predicate].append(obj)
    return graph


def _one(props: dict[str, list[Term]], name: str, subject: str) -> Term | None:
    values = props.get(AC + name, [])
    if len(values) > 1:
        raise AccessContractError(f"{subject}: ac:{name} appears more than once")
    return values[0] if values else None


def _text(props: dict[str, list[Term]], name: str, subject: str) -> str:
    value = _one(props, name, subject)
    if not isinstance(value, str) or not value.strip():
        raise AccessContractError(f"{subject}: missing ac:{name}")
    return value


def _int(props: dict[str, list[Term]], name: str, subject: str) -> int | None:
    value = _one(props, name, subject)
    if value is not None and (not isinstance(value, int) or value < 0):
        raise AccessContractError(
            f"{subject}: ac:{name} must be a non-negative integer"
        )
    return value


def _choice(value: str, allowed: frozenset[str], name: str, subject: str) -> str:
    if value not in allowed:
        raise AccessContractError(f"{subject}: unknown ac:{name} {value!r}")
    return value


def _auth_ref(props: dict[str, list[Term]], subject: str) -> str | None:
    value = _one(props, "authRef", subject)
    if value is None:
        return None
    try:
        return parse_secret_reference(str(value)).render()
    except SecretReferenceError:
        raise AccessContractError(
            f"{subject}: ac:authRef must be a credential reference, not a secret"
        ) from None


def _bindings(
    graph: dict[str, dict[str, list[Term]]], contract: str
) -> tuple[tuple[str, str], ...]:
    pairs = []
    for subject, props in graph.items():
        if contract in props.get(AC + "contract", []):
            prop = _text(props, "property", subject)
            pairs.append((prop, _text(props, "field", subject)))
    return tuple(sorted(pairs))


def _contract(graph: dict[str, dict[str, list[Term]]], subject: str) -> AccessContract:
    props = graph[subject]
    pushdown = frozenset(str(op) for op in props.get(AC + "pushdown", []))
    unknown = sorted(pushdown - PUSHDOWN_OPS)
    if unknown:
        raise AccessContractError(f"{subject}: unknown ac:pushdown {unknown}")
    kind = _choice(
        _text(props, "accessKind", subject), ACCESS_KINDS, "accessKind", subject
    )
    pagination = _one(props, "pagination", subject) or "none"
    cost = _one(props, "costHint", subject) or "unknown"
    return AccessContract(
        contract_iri=subject,
        class_iri=_text(props, "classIri", subject),
        source_id=_text(props, "sourceId", subject),
        entity=_text(props, "entity", subject),
        key_field=_text(props, "keyField", subject),
        access_kind=kind,
        operation=_text(props, "operation", subject),
        parameters=tuple(sorted(str(p) for p in props.get(AC + "parameter", []))),
        pagination=_choice(str(pagination), PAGINATION_MODES, "pagination", subject),
        pushdown=pushdown,
        auth_ref=_auth_ref(props, subject),
        rate_limit_per_minute=_int(props, "rateLimitPerMinute", subject),
        freshness_seconds=_int(props, "freshnessSeconds", subject),
        cost_hint=_choice(str(cost), COST_HINTS | {"unknown"}, "costHint", subject),
        predicates=_bindings(graph, subject),
    )


def parse_access_contracts(turtle: str) -> tuple[AccessContract, ...]:
    """Parse every ``ac:AccessContract`` declared in one connector ontology.

    Raises:
        AccessContractError: for unsupported Turtle or an invalid contract.
    """
    graph = _index(_Reader(turtle).read())
    subjects = sorted(
        s
        for s, props in graph.items()
        if AC + "AccessContract" in props.get(_RDF_TYPE, [])
    )
    return tuple(_contract(graph, s) for s in subjects)
