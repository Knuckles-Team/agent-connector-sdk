"""The shared GraphQL client for connectors (SCION-CONNECTOR-CONTROL-R030.1).

One client owns the GraphQL transport for every connector with a GraphQL
backend: the endpoint, an auth header strategy (bearer, token or basic), the
TLS profile from :func:`agent_connector_sdk.tls.resolve.resolve_tls_profile`,
a request timeout, a bounded retry on HTTP 429 and 5xx, a cursor pagination
helper, and a sync and an async execute.

A failure never carries the server's error text or the request: it raises
:class:`GraphQLExecutionError`, whose message names only the exception class,
and whose :meth:`GraphQLExecutionError.payload` matches
:func:`agent_connector_sdk.mcp.graphql.graphql_failure_payload` (class and
correlation id). The exception message is not logged.

Install the ``graphql`` extra: ``scion-sdk[graphql]``.
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio

from agent_connector_sdk.exceptions import ParameterError
from agent_connector_sdk.tls.profile import ResolvedTLSProfile
from agent_connector_sdk.tls.resolve import resolve_tls_profile

__all__ = [
    "RETRYABLE_STATUS",
    "GraphQLAuth",
    "GraphQLClient",
    "GraphQLExecutionError",
]

_logger = logging.getLogger(__name__)

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


class GraphQLClient:
    """One GraphQL endpoint with auth, TLS, timeout and bounded retry.

    Args:
        endpoint: The full GraphQL URL.
        auth: The auth header strategy; no auth header when omitted.
        headers: Extra static headers (for example an ``Origin``).
        tls_profile: A resolved TLS profile; resolved from ``tls_service``
            when omitted.
        tls_service: The settings prefix for ``resolve_tls_profile``.
        timeout: Seconds per request.
        max_retries: Extra attempts after a 429/5xx response (bounded).
        backoff: Base seconds for exponential backoff between attempts.
        fetch_schema: Fetch the schema by introspection on first use and
            validate documents locally; :attr:`schema` then holds it.
        sleep: Injected for tests.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        auth: GraphQLAuth | None = None,
        headers: Mapping[str, str] | None = None,
        tls_profile: ResolvedTLSProfile | None = None,
        tls_service: str = "graphql",
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        fetch_schema: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not endpoint:
            raise ParameterError("GraphQL endpoint is required")
        if max_retries < 0 or max_retries > 10:
            raise ParameterError("max_retries must be between 0 and 10")
        self.endpoint = endpoint
        self.auth = auth or GraphQLAuth.none()
        self.headers: dict[str, str] = {**dict(headers or {}), **self.auth.headers()}
        self.tls_profile = tls_profile or resolve_tls_profile(tls_service)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.fetch_schema = fetch_schema
        self._sleep = sleep
        self.last_partial_error_count = 0
        self._client: Any = None

    # -- transport -----------------------------------------------------------
    def _build_client(self) -> Any:
        from gql import Client
        from gql.transport.requests import RequestsHTTPTransport

        profile = self.tls_profile

        class _ProfiledTransport(RequestsHTTPTransport):
            def connect(self) -> None:
                super().connect()  # type: ignore[no-untyped-call]
                if self.session is not None:
                    profile.configure_requests_session(self.session)

        request_kwargs = profile.requests_kwargs()
        verify = request_kwargs.pop("verify")
        transport = _ProfiledTransport(
            url=self.endpoint,
            headers=self.headers,
            verify=verify,
            timeout=max(1, round(self.timeout)),
            **request_kwargs,
        )
        return Client(
            transport=transport,
            fetch_schema_from_transport=self.fetch_schema,
            execute_timeout=self.timeout,
        )

    @property
    def client(self) -> Any:
        """The underlying protocol client, built on first use."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    @property
    def schema(self) -> Any:
        """The introspected schema (``fetch_schema=True``), else ``None``."""
        return getattr(self.client, "schema", None)

    # -- execute -------------------------------------------------------------
    def _attempt(
        self,
        document: str,
        variables: Mapping[str, Any] | None,
        operation_name: str | None,
        allow_partial: bool,
    ) -> dict[str, Any]:
        from gql import gql

        query = gql(document)
        if not allow_partial:
            self.last_partial_error_count = 0
            result = self.client.execute(
                query,
                variable_values=dict(variables) if variables else None,
                operation_name=operation_name,
            )
            return dict(result)
        execution = self.client.execute(
            query,
            variable_values=dict(variables) if variables else None,
            operation_name=operation_name,
            get_execution_result=True,
        )
        errors = getattr(execution, "errors", None) or []
        self.last_partial_error_count = len(errors)
        if errors:
            _logger.warning(
                "GraphQL returned %d field-level error(s); using partial data",
                len(errors),
            )
        data = getattr(execution, "data", None)
        if not isinstance(data, dict):
            raise ParameterError("GraphQL returned no usable data")
        return data

    def execute(
        self,
        document: str,
        variables: Mapping[str, Any] | None = None,
        operation_name: str | None = None,
        *,
        allow_partial: bool = False,
    ) -> dict[str, Any]:
        """Run one query or mutation and return its ``data``.

        ``allow_partial`` returns usable data when the server also reports
        field-level errors; the error content is never returned or logged.

        Raises:
            GraphQLExecutionError: the request failed after bounded retries.
        """
        attempt = 0
        while True:
            try:
                return self._attempt(document, variables, operation_name, allow_partial)
            except Exception as exc:
                status = _status_of(exc)
                retryable = status in RETRYABLE_STATUS
                if retryable and attempt < self.max_retries:
                    self._sleep(self.backoff * (2**attempt))
                    attempt += 1
                    continue
                failure = GraphQLExecutionError(exc, retryable=retryable)
            raise failure

    async def execute_async(
        self,
        document: str,
        variables: Mapping[str, Any] | None = None,
        operation_name: str | None = None,
        *,
        allow_partial: bool = False,
    ) -> dict[str, Any]:
        """:meth:`execute` on a worker thread, for async tools."""

        def _run() -> dict[str, Any]:
            return self.execute(
                document, variables, operation_name, allow_partial=allow_partial
            )

        return await anyio.to_thread.run_sync(_run)

    # -- pagination ----------------------------------------------------------
    def paginate(
        self,
        document: str,
        connection_path: Sequence[str],
        variables: Mapping[str, Any] | None = None,
        *,
        cursor_variable: str = "after",
        max_pages: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Yield each node of a cursor connection across pages.

        ``connection_path`` names the keys from ``data`` to the connection
        (for example ``("project", "issues")``). The connection carries
        ``nodes`` (or ``edges[].node``) and ``pageInfo{hasNextPage endCursor}``.
        Stops after ``max_pages`` pages, so a server that never ends is bounded.
        """
        page_variables = dict(variables or {})
        for _ in range(max_pages):
            data: Any = self.execute(document, page_variables)
            for key in connection_path:
                data = data.get(key) if isinstance(data, dict) else None
            if not isinstance(data, dict):
                return
            nodes = data.get("nodes")
            if nodes is None:
                nodes = [
                    edge.get("node")
                    for edge in data.get("edges") or []
                    if isinstance(edge, dict)
                ]
            for node in nodes or []:
                if isinstance(node, dict):
                    yield node
            page_info = data.get("pageInfo") or {}
            cursor = page_info.get("endCursor")
            if not page_info.get("hasNextPage") or not cursor:
                return
            page_variables[cursor_variable] = cursor

    def close(self) -> None:
        """Release the transport session and runtime-only TLS material."""
        client = self._client
        if client is not None and hasattr(client, "session"):
            try:
                client.close_sync()
            except Exception:  # best-effort release; upstream details may be secret
                _logger.debug("GraphQL client close failed")
        self.tls_profile.cleanup()
