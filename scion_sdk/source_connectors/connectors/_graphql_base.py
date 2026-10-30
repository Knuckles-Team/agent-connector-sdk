"""Shared error and bounds for the GraphQL document connector."""

from __future__ import annotations

_MAX_GRAPHQL_TOKENS = 20_000


class GraphQLDocumentError(RuntimeError):
    """A source-safe GraphQL connector failure with no upstream payload text."""


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constants are not supported")
