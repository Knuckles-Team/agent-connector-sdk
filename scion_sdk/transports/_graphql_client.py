"""Protocol-client construction for the GraphQL transport."""

from __future__ import annotations

from typing import Any

from scion_sdk.tls.profile import ResolvedTLSProfile


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
