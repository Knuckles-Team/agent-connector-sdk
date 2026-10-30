"""Bounded GraphQL query-document validation for the document connector."""

from __future__ import annotations

from typing import Any

from graphql import GraphQLError, parse
from graphql.language import (
    ArgumentNode,
    FieldNode,
    FragmentDefinitionNode,
    InlineFragmentNode,
    Node,
    OperationDefinitionNode,
    OperationType,
    SelectionNode,
    VariableNode,
)

from ._graphql_base import _MAX_GRAPHQL_TOKENS, GraphQLDocumentError

_PARSE_ERRORS = (GraphQLError, RecursionError, TypeError, ValueError)


def _parse_graphql(query: str) -> Any:
    return parse(
        query,
        no_location=True,
        max_tokens=_MAX_GRAPHQL_TOKENS,
        # graphql-core 3.3.0 removed the deprecated `allow_legacy_fragment_variables`
        # parser option (GraphQL.js v17); its replacement defaults to the same
        # deny-by-default posture this bounded parse relies on.
        experimental_fragment_arguments=False,
    )


def _parse_bounded_query(query: str) -> Any:
    """Enforce the size/emptiness bounds, then parse via the GraphQL AST."""
    if len(query.encode("utf-8")) > 200_000:
        raise GraphQLDocumentError("GraphQL query exceeds the configured bound")
    if not query:
        raise GraphQLDocumentError("GraphQL operation must be a read query")
    try:
        return _parse_graphql(query)
    except _PARSE_ERRORS:
        raise GraphQLDocumentError(
            "GraphQL operation is not a valid document"
        ) from None


def _ensure_single_read_query(document: Any) -> None:
    operations = [
        definition
        for definition in document.definitions
        if isinstance(definition, OperationDefinitionNode)
    ]
    if len(operations) != 1 or operations[0].operation is not OperationType.QUERY:
        raise GraphQLDocumentError("GraphQL operation must be a read query")
    if any(
        not isinstance(definition, OperationDefinitionNode | FragmentDefinitionNode)
        for definition in document.definitions
    ):
        raise GraphQLDocumentError("GraphQL operation contains unsupported definitions")


def _document_selections(document: Any) -> list[SelectionNode]:
    selections: list[SelectionNode] = []
    for definition in document.definitions:
        if isinstance(definition, OperationDefinitionNode | FragmentDefinitionNode):
            selections.extend(definition.selection_set.selections)
    return selections


def _reject_introspection(document: Any, *, allow_introspection: bool) -> None:
    selections = _document_selections(document)
    while selections:
        selection = selections.pop()
        if (
            isinstance(selection, FieldNode)
            and selection.name.value in {"__schema", "__type"}
            and not allow_introspection
        ):
            raise GraphQLDocumentError(
                "GraphQL introspection is not an ingest operation"
            )
        if isinstance(selection, FieldNode | InlineFragmentNode):
            selection_set = selection.selection_set
            if selection_set is not None:
                selections.extend(selection_set.selections)


def _validate_query_document(value: Any, *, allow_introspection: bool = False) -> str:
    """Accept exactly one bounded query operation without echoing its text.

    The AST is the authority.  Keyword regexes are not sufficient here: operation
    names, comments, string literals, fragments, and multi-operation documents can
    all make a lexical classifier disagree with what a GraphQL server executes.
    """
    query = str(value or "").strip()
    document = _parse_bounded_query(query)
    _ensure_single_read_query(document)
    _reject_introspection(document, allow_introspection=allow_introspection)
    return query


def _is_row_bound_argument(node: Node, variable: str) -> bool:
    return (
        isinstance(node, ArgumentNode)
        and node.name.value in {"first", "limit"}
        and isinstance(node.value, VariableNode)
        and node.value.name.value == variable
    )


def _node_children(node: Node) -> list[Node]:
    children: list[Node] = []
    for key in node.keys:
        child = getattr(node, key, None)
        if isinstance(child, tuple):
            children.extend(item for item in child if isinstance(item, Node))
        elif isinstance(child, Node):
            children.append(child)
    return children


def _query_binds_row_bound(query: str, variable: str) -> bool:
    """Prove the variable is used by a conventional row-bound argument."""

    try:
        document = _parse_graphql(query)
    except _PARSE_ERRORS:
        return False
    stack: list[Node] = [
        definition
        for definition in document.definitions
        if isinstance(definition, Node)
    ]
    while stack:
        node = stack.pop()
        if _is_row_bound_argument(node, variable):
            return True
        stack.extend(_node_children(node))
    return False
