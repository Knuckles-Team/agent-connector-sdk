"""Shared error and bounds for the GraphQL document connector."""

from __future__ import annotations

import re

_MAX_GRAPHQL_TOKENS = 20_000


class GraphQLDocumentError(RuntimeError):
    """A source-safe GraphQL connector failure with no upstream payload text."""


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constants are not supported")


_ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_DOCUMENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SECRET_REF_RE = re.compile(r"^(?:env|openbao)://[A-Za-z0-9_./#-]+$")
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_FIELD_NAME_RE = re.compile(r"^[_A-Za-z][_0-9A-Za-z]{0,127}$")
_FIELD_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_RETENTION_RE = re.compile(
    r"^(?:P(?:\d+[YMWD])+(?:T(?:\d+[HMS])+)?)|[A-Za-z][A-Za-z0-9_.:-]{1,63}$"
)
_VERSION_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_HEADER_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
_BLOCKED_REQUEST_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_MAX_PROFILE_BYTES = 8 * 1024 * 1024
_CHECKPOINT_FORMAT = "graphql-snapshot-checkpoint/v1"
_ENTITY_KINDS = ("entity", "hierarchy", "document", "application", "dependency")
_MAPPING_KEYS = {
    "entity": ("entity", "entities"),
    "hierarchy": ("hierarchy", "hierarchies"),
    "document": ("document", "documents"),
    "application": ("application", "applications"),
    "dependency": ("dependency", "dependencies"),
}
_DEFAULT_ENTITY_TYPES = {
    "entity": "ExternalEntity",
    "hierarchy": "ExternalHierarchy",
    "document": "Document",
    "application": "Application",
    "dependency": "Dependency",
}
