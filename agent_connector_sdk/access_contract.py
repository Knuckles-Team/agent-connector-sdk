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

from dataclasses import dataclass, field
from importlib import resources

from . import _contract_fields as f
from ._contract_fields import (
    AC,
    ACCESS_KINDS,
    COST_HINTS,
    PAGINATION_MODES,
    PUSHDOWN_OPS,
)
from ._turtle import RDF_TYPE, AccessContractError, parse_graph

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


def _contract(graph: dict[str, f.Props], subject: str) -> AccessContract:
    props = graph[subject]
    return AccessContract(
        contract_iri=subject,
        class_iri=f.text(props, "classIri", subject),
        source_id=f.text(props, "sourceId", subject),
        entity=f.text(props, "entity", subject),
        key_field=f.text(props, "keyField", subject),
        access_kind=f.choice(props, "accessKind", subject, allowed=ACCESS_KINDS),
        operation=f.text(props, "operation", subject),
        parameters=f.parameters(props),
        pagination=f.choice(
            props, "pagination", subject, allowed=PAGINATION_MODES, default="none"
        ),
        pushdown=f.pushdown(props, subject),
        auth_ref=f.auth_ref(props, subject),
        rate_limit_per_minute=f.integer(props, "rateLimitPerMinute", subject),
        freshness_seconds=f.integer(props, "freshnessSeconds", subject),
        cost_hint=f.choice(
            props,
            "costHint",
            subject,
            allowed=COST_HINTS | {"unknown"},
            default="unknown",
        ),
        predicates=f.bindings(graph, subject),
    )


def parse_access_contracts(turtle: str) -> tuple[AccessContract, ...]:
    """Parse every ``ac:AccessContract`` declared in one connector ontology.

    Raises:
        AccessContractError: for unsupported Turtle or an invalid contract.
    """
    graph = parse_graph(turtle)
    subjects = sorted(
        s
        for s, props in graph.items()
        if AC + "AccessContract" in props.get(RDF_TYPE, [])
    )
    return tuple(_contract(graph, s) for s in subjects)
