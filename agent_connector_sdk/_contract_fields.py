"""Typed field readers for ``ac:AccessContract`` subjects."""

from __future__ import annotations

from ._turtle import AccessContractError, Term
from .credentials.references import SecretReferenceError, parse_secret_reference

AC = "https://knuckles-team.github.io/agent-connector-sdk/access#"
ACCESS_KINDS = frozenset({"mcp_tool", "http_endpoint", "graphql_query", "a2a_skill"})
PAGINATION_MODES = frozenset({"none", "cursor", "offset", "page"})
PUSHDOWN_OPS = frozenset({"filter", "sort", "limit", "project"})
COST_HINTS = frozenset({"low", "medium", "high"})

Props = dict[str, list[Term]]


def _one(props: Props, name: str, subject: str) -> Term | None:
    values = props.get(AC + name, [])
    if len(values) > 1:
        raise AccessContractError(f"{subject}: ac:{name} appears more than once")
    return values[0] if values else None


def text(props: Props, name: str, subject: str) -> str:
    """Return a required non-empty string property."""
    value = _one(props, name, subject)
    if not isinstance(value, str) or not value.strip():
        raise AccessContractError(f"{subject}: missing ac:{name}")
    return value


def integer(props: Props, name: str, subject: str) -> int | None:
    """Return an optional non-negative integer property."""
    value = _one(props, name, subject)
    if value is not None and (not isinstance(value, int) or value < 0):
        raise AccessContractError(
            f"{subject}: ac:{name} must be a non-negative integer"
        )
    return value


def choice(
    props: Props,
    name: str,
    subject: str,
    *,
    allowed: frozenset[str],
    default: str | None = None,
) -> str:
    """Return a property constrained to ``allowed``; ``default`` makes it optional."""
    raw = _one(props, name, subject) if default is not None else None
    value = text(props, name, subject) if default is None else str(raw or default)
    if value not in allowed:
        raise AccessContractError(f"{subject}: unknown ac:{name} {value!r}")
    return value


def pushdown(props: Props, subject: str) -> frozenset[str]:
    """Return the declared pushdown operations, refusing unknown ones."""
    ops = frozenset(str(op) for op in props.get(AC + "pushdown", []))
    unknown = sorted(ops - PUSHDOWN_OPS)
    if unknown:
        raise AccessContractError(f"{subject}: unknown ac:pushdown {unknown}")
    return ops


def parameters(props: Props) -> tuple[str, ...]:
    """Return the declared operation parameters in sorted order."""
    return tuple(sorted(str(p) for p in props.get(AC + "parameter", [])))


def auth_ref(props: Props, subject: str) -> str | None:
    """Return a rendered credential reference, refusing a literal secret."""
    value = _one(props, "authRef", subject)
    if value is None:
        return None
    try:
        return parse_secret_reference(str(value)).render()
    except SecretReferenceError:
        raise AccessContractError(
            f"{subject}: ac:authRef must be a credential reference, not a secret"
        ) from None


def bindings(graph: dict[str, Props], contract: str) -> tuple[tuple[str, str], ...]:
    """Return the sorted (property, field) pairs bound to ``contract``."""
    pairs = []
    for subject, props in graph.items():
        if contract in props.get(AC + "contract", []):
            prop = text(props, "property", subject)
            pairs.append((prop, text(props, "field", subject)))
    return tuple(sorted(pairs))
