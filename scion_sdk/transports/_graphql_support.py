"""Support types and helpers for :mod:`scion_sdk.transports.graphql`."""

from __future__ import annotations

import base64
import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from scion_sdk.exceptions import ParameterError
from scion_sdk.tls.profile import ResolvedTLSProfile

_logger = logging.getLogger("scion_sdk.transports.graphql")

#: HTTP statuses retried with backoff; every other failure fails at once.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class GraphQLAuth:
    """One auth header. ``repr`` never shows the credential."""

    header: str = ""
    value: str = field(default="", repr=False)

    @classmethod
    def none(cls) -> GraphQLAuth:
        return cls()

    @classmethod
    def bearer(cls, token: str) -> GraphQLAuth:
        """``Authorization: Bearer <token>``."""
        return cls("Authorization", f"Bearer {token}")

    @classmethod
    def token(
        cls, token: str, *, header: str = "Authorization", prefix: str = "token"
    ) -> GraphQLAuth:
        """``<header>: <prefix> <token>``; an empty prefix sends the raw token."""
        return cls(header, f"{prefix} {token}" if prefix else token)

    @classmethod
    def basic(cls, username: str, password: str) -> GraphQLAuth:
        """``Authorization: Basic base64(username:password)``."""
        raw = f"{username}:{password}".encode()
        return cls("Authorization", "Basic " + base64.b64encode(raw).decode("ascii"))

    def headers(self) -> dict[str, str]:
        return {self.header: self.value} if self.header and self.value else {}


class GraphQLExecutionError(ParameterError):
    """A redacted GraphQL failure: exception class and correlation id only."""

    def __init__(self, exc: BaseException, *, retryable: bool = False) -> None:
        self.error_class = type(exc).__name__
        self.correlation_id = uuid.uuid4().hex
        self.retryable = retryable
        _logger.warning(
            "GraphQL execution failed (correlation_id=%s, error_class=%s)",
            self.correlation_id,
            self.error_class,
        )
        super().__init__(f"Query execution failed: {self.error_class}")

    def payload(self) -> dict[str, Any]:
        """The public failure payload, shaped like ``graphql_failure_payload``."""
        return {
            "status": "error",
            "code": "operation_failed",
            "retryable": self.retryable,
            "error_class": self.error_class,
            "correlation_id": self.correlation_id,
        }


def _status_of(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def _retry_or_failure(
    exc: BaseException,
    attempt: int,
    max_retries: int,
    backoff: float,
    sleep: Callable[[float], None],
) -> GraphQLExecutionError | None:
    """Back off and return ``None`` to retry, else the redacted failure to raise."""
    retryable = _status_of(exc) in RETRYABLE_STATUS
    if retryable and attempt < max_retries:
        sleep(backoff * (2**attempt))
        return None
    return GraphQLExecutionError(exc, retryable=retryable)


def _build_profiled_client(
    endpoint: str,
    *,
    headers: dict[str, str],
    profile: ResolvedTLSProfile,
    timeout: float,
    fetch_schema: bool,
) -> Any:
    """Build the protocol client whose session carries the TLS profile."""
    from gql import Client
    from gql.transport.requests import RequestsHTTPTransport

    class _ProfiledTransport(RequestsHTTPTransport):
        def connect(self) -> None:
            super().connect()  # type: ignore[no-untyped-call]
            if self.session is not None:
                profile.configure_requests_session(self.session)

    request_kwargs = profile.requests_kwargs()
    verify = request_kwargs.pop("verify")
    transport = _ProfiledTransport(
        url=endpoint,
        headers=headers,
        verify=verify,
        timeout=max(1, round(timeout)),
        **request_kwargs,
    )
    return Client(
        transport=transport,
        fetch_schema_from_transport=fetch_schema,
        execute_timeout=timeout,
    )


def _connection_at(data: Any, path: Sequence[str]) -> dict[str, Any] | None:
    """The connection object ``path`` keys below ``data``, or ``None``."""
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, dict) else None


def _connection_nodes(connection: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Each node of a connection's ``nodes`` (or ``edges[].node``)."""
    nodes = connection.get("nodes")
    if nodes is None:
        nodes = [
            edge.get("node")
            for edge in connection.get("edges") or []
            if isinstance(edge, dict)
        ]
    for node in nodes or []:
        if isinstance(node, dict):
            yield node


def _next_cursor(connection: dict[str, Any]) -> str | None:
    """The ``endCursor`` when another page follows, else ``None``."""
    page_info = connection.get("pageInfo") or {}
    cursor = page_info.get("endCursor")
    return cursor if page_info.get("hasNextPage") and cursor else None
