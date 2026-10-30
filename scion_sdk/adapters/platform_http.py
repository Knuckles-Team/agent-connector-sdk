"""Governed one-attempt HTTP adapter for certified platform reads."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from types import MappingProxyType
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from scion_sdk.adapters.platform_backend import BackendFailure, BackendPage
from scion_sdk.adapters.platform_models import (
    BackendPolicy,
    PlatformRequest,
    Reason,
)
from scion_sdk.http.bodies import aread_bounded
from scion_sdk.http.client import create_async_http_client
from scion_sdk.http.egress import EgressPolicyError, PinnedEgressViolation
from scion_sdk.http.errors import (
    HttpProblemError,
    ResponseTooLargeError,
    TlsVerificationError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import parse_retry_after

MAX_PLATFORM_RESPONSE_BYTES = 1_048_576


class PlatformHttpBackend:
    """One governed request for a connector's admitted HTTP backend.

    Construction does not certify the adapter or authorize a caller. The
    caller's admission authority must verify adapter identity and policy.
    """

    def __init__(
        self,
        policy: BackendPolicy,
        options: HttpClientOptions,
        path: str,
        *,
        output_model: type[BaseModel],
    ) -> None:
        options = replace(
            options,
            headers=MappingProxyType(dict(options.headers)),
            allowed_private_hosts=tuple(options.allowed_private_hosts),
        )
        host = urlsplit(options.base_url).hostname
        if (
            host is None
            or host.lower()
            not in {item.lower() for item in policy.allowed_destinations}
            or not options.pin_egress
            or options.retry.max_attempts != 1
            or ((policy.auth_mode == "credential") != (options.auth is not None))
            or not path.startswith("/")
            or path.startswith("//")
            or "?" in path
            or "#" in path
        ):
            raise ValueError("platform backend does not match its egress policy")
        self._policy = policy
        self._output_model = output_model
        self._options = options
        self._path = path

    @property
    def policy(self) -> BackendPolicy:
        """The exact policy this adapter was configured to enforce."""
        return self._policy

    @property
    def output_model(self) -> type[BaseModel]:
        """The declared model used to validate each returned record."""
        return self._output_model

    async def read(self, request: PlatformRequest, *, timeout_ms: int) -> BackendPage:
        """Perform one network attempt and parse its bounded response."""
        params = {"limit": str(request.limit)}
        if request.query is not None:
            params["query"] = request.query
        if request.target is not None:
            params["target"] = request.target
        if request.continuation is not None:
            params["continuation"] = request.continuation.token
        failure: BackendFailure | None = None
        body = b""
        try:
            async with (
                create_async_http_client(self._options) as client,
                client.stream(
                    "GET",
                    self._path,
                    params=params,
                    headers={"Accept-Encoding": "identity"},
                    timeout=timeout_ms / 1000,
                ) as response,
            ):
                status = response.status_code
                if status != 200:
                    if status in (401, 403):
                        raise BackendFailure("unauthorized", http_status=status)
                    if status == 404:
                        raise BackendFailure("not_found", http_status=status)
                    if status == 429:
                        retry_after = parse_retry_after(
                            response.headers.get("retry-after")
                        )
                        wait = (
                            None
                            if retry_after is None
                            else (
                                min(30_000, int(retry_after * 1000))
                                if isfinite(retry_after) and retry_after < 30
                                else 30_000
                            )
                        )
                        raise BackendFailure(
                            "rate_limited", http_status=status, retry_after_ms=wait
                        )
                    reason: Reason = (
                        "upstream_unavailable"
                        if status == 408 or status >= 500
                        else "invalid_response"
                    )
                    raise BackendFailure(reason, http_status=status)
                if (
                    response.headers.get("content-encoding", "identity").lower()
                    != "identity"
                ):
                    raise BackendFailure("invalid_response")
                body = await aread_bounded(response, MAX_PLATFORM_RESPONSE_BYTES)
        except (EgressPolicyError, PinnedEgressViolation):
            failure = BackendFailure("egress_denied")
        except TlsVerificationError:
            failure = BackendFailure("trust_failed")
        except (UpstreamTimeoutError, httpx.TimeoutException):
            failure = BackendFailure("timeout")
        except (UpstreamUnavailableError, httpx.NetworkError):
            failure = BackendFailure("connection_failed")
        except (ResponseTooLargeError, HttpProblemError):
            failure = BackendFailure("invalid_response")
        if failure is not None:
            raise failure
        try:
            page = BackendPage.model_validate_json(body)
        except ValidationError:
            failure = BackendFailure("invalid_response")
        if failure is not None:
            raise failure
        return page
