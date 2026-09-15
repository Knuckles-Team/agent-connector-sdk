"""Client-credentials auth to MCP endpoints: a local issuer and a token-checking server."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx2
import pytest
import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError

from agent_connector_sdk.auth.client_credentials import ClientCredentialsTokenProvider
from agent_connector_sdk.auth.oidc import (
    ClientCredentialsConfig,
    client_credentials_auth,
    discover_token_endpoint,
)
from agent_connector_sdk.auth.tokens import TokenRequestError
from agent_connector_sdk.credentials.resolver import EnvironmentCredentialResolver
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor, EndpointSpec
from agent_connector_sdk.runner.endpoints import CredentialEndpoints
from agent_connector_sdk.runner.errors import CredentialResolutionError
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.transports.mcp import McpTransport

_CLIENT_CREDENTIAL = "fleet-client-credential-value"
_JSON = {"Content-Type": "application/json"}


def _json(document: object) -> ScriptedResponse:
    return ScriptedResponse(body=json.dumps(document).encode(), headers=_JSON)


def _token(value: str, ttl: int = 300) -> ScriptedResponse:
    return _json({"access_token": value, "token_type": "Bearer", "expires_in": ttl})


class _FleetVerifier(TokenVerifier):
    """Accepts only tokens the test marks valid, like a fleet server's JWT check."""

    def __init__(self) -> None:
        super().__init__()
        self.valid: set[str] = set()
        self.presented: list[str] = []

    async def verify_token(self, token: str) -> AccessToken | None:
        self.presented.append(token)
        if token not in self.valid:
            return None
        return AccessToken(token=token, client_id="connector-sync", scopes=[])


@contextmanager
def _fleet_server(verifier: _FleetVerifier) -> Iterator[str]:
    mcp = FastMCP("fleet-fixture", auth=verifier)

    @mcp.tool
    def ping() -> str:
        """Answer pong."""
        return "pong"

    ready = threading.Event()
    config = uvicorn.Config(
        mcp.http_app(),
        host="127.0.0.1",
        port=0,
        log_level="error",
        lifespan="on",
        callback_notify=AsyncMock(side_effect=ready.set),
        timeout_notify=1,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not ready.wait(60):
        server.should_exit = True
        thread.join(15)
        pytest.fail("fixture MCP server did not become ready within 60 seconds")
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(15)


@pytest.fixture
def issuer() -> Iterator[ScriptedHttpServer]:
    with ScriptedHttpServer() as server:
        server.enqueue(
            _json(
                {
                    "issuer": server.base_url,
                    "token_endpoint": f"{server.base_url}/token",
                }
            )
        )
        yield server


def _descriptor(
    tmp_path: Path, url: str, config: ClientCredentialsConfig
) -> ConnectorDescriptor:
    spec = EndpointSpec(url=url, client_credentials=config)
    return ConnectorDescriptor(
        connector="fleet-fixture", package_root=tmp_path, endpoint=spec
    )


async def _tool_names(endpoint: TransportEndpoint) -> list[str]:
    async with McpTransport().session(endpoint) as session:
        return [tool.name for tool in await session.list_tools()]


async def test_runner_endpoint_acquires_caches_and_remints_on_401(
    tmp_path: Path,
    issuer: ScriptedHttpServer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("FLEET_CLIENT_SECRET", _CLIENT_CREDENTIAL)
    config = ClientCredentialsConfig(
        issuer=issuer.base_url,
        client_id="connector-sync",
        client_secret_ref="env://FLEET_CLIENT_SECRET",
        audience="agent-services",
        scope="mcp:tools",
    )
    issuer.enqueue(_token("fleet-token-one"), _token("fleet-token-two"))
    verifier = _FleetVerifier()
    verifier.valid = {"fleet-token-one"}
    endpoints = CredentialEndpoints(EnvironmentCredentialResolver())
    with _fleet_server(verifier) as url:
        with pytest.raises(MCPError):
            await _tool_names(TransportEndpoint(url=url))
        assert verifier.presented == []
        descriptor = _descriptor(tmp_path, url, config)
        endpoint = endpoints(descriptor)
        assert await _tool_names(endpoint) == ["ping"]
        assert await _tool_names(endpoints(descriptor)) == ["ping"]
        assert len(issuer.requests) == 2
        verifier.valid = {"fleet-token-two"}
        assert await _tool_names(endpoints(descriptor)) == ["ping"]
    assert len(issuer.requests) == 3
    grant = issuer.requests[1].body.decode()
    assert (
        "grant_type=client_credentials" in grant and "audience=agent-services" in grant
    )
    assert (
        "fleet-token-one" in verifier.presented
        and verifier.presented[-1] == "fleet-token-two"
    )
    assert _CLIENT_CREDENTIAL not in caplog.text and "fleet-token" not in caplog.text
    assert "fleet-token" not in repr(endpoint)


def test_refresh_before_expiry(
    issuer: ScriptedHttpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLEET_CLIENT_SECRET", _CLIENT_CREDENTIAL)
    issuer.enqueue(_token("short-lived", ttl=31), _token("replacement"))
    config = ClientCredentialsConfig(
        issuer=issuer.base_url,
        client_id="connector-sync",
        client_secret_ref="env://FLEET_CLIENT_SECRET",
    )
    provider: ClientCredentialsTokenProvider = client_credentials_auth(config).provider
    assert provider.get_token() == "short-lived"
    time.sleep(1.1)
    assert provider.get_token() == "replacement"


def test_token_failures_fail_the_endpoint_closed(
    tmp_path: Path, issuer: ScriptedHttpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FLEET_CLIENT_SECRET", raising=False)
    config = ClientCredentialsConfig(
        issuer=issuer.base_url,
        client_id="connector-sync",
        client_secret_ref="env://FLEET_CLIENT_SECRET",
    )
    endpoints = CredentialEndpoints(EnvironmentCredentialResolver())
    descriptor = _descriptor(tmp_path, "https://mcp.example.invalid/mcp", config)
    with pytest.raises(
        CredentialResolutionError, match="client-credentials token"
    ) as raised:
        endpoints(descriptor)
    assert "FLEET_CLIENT_SECRET" not in str(raised.value)


def test_discovery_failures(issuer: ScriptedHttpServer) -> None:
    issuer.next_response()
    issuer.enqueue(
        _json({"token_endpoint": "http://idp.example.invalid/token"}),
        ScriptedResponse(status=500),
    )
    with create_http_client(HttpClientOptions(base_url=issuer.base_url)) as client:
        with pytest.raises(TokenRequestError, match="no usable"):
            discover_token_endpoint(issuer.base_url, client)
        with pytest.raises(TokenRequestError, match="discovery failed"):
            discover_token_endpoint(issuer.base_url, client)


def test_client_credentials_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "OIDC_ISSUER": "https://idp.example.invalid/realms/fleet, https://other.example.invalid",
        "OIDC_CLIENT_ID": "connector-sync",
        "OIDC_CLIENT_SECRET_REF": "openbao://apps/connector-sync#OIDC_CLIENT_SECRET",
        "OIDC_AUDIENCE": "agent-services",
        "OIDC_SCOPE": "mcp:tools",
    }.items():
        monkeypatch.setenv(name, value)
    config = ClientCredentialsConfig.from_settings()
    assert (
        config.issuer == "https://idp.example.invalid/realms/fleet"
        and config.scope == "mcp:tools"
    )
    base = {"client_id": "c", "client_secret_ref": "env://S"}
    for invalid in (
        {
            **base,
            "issuer": "https://a.example.invalid",
            "token_url": "https://a.example.invalid/t",
        },
        {**base},
        {**base, "token_url": "http://idp.example.invalid/token"},
        {**base, "token_url": "https://idp.example.invalid/token?x=1"},
        {
            "client_id": "c",
            "client_secret_ref": "literal-secret",
            "token_url": "https://a.example.invalid/t",
        },
    ):
        with pytest.raises((ValidationError, ValueError)):
            ClientCredentialsConfig.model_validate(invalid)


def test_endpoint_auth_rules() -> None:
    auth = httpx2.BasicAuth("u", "p")
    assert "BasicAuth" not in repr(
        TransportEndpoint(url="https://mcp.example.invalid/mcp", auth=auth)
    )
    with pytest.raises(ValueError, match="auth applies only"):
        TransportEndpoint(command="demo-mcp", auth=auth)
    with pytest.raises(ValueError, match="at most one"):
        TransportEndpoint(
            url="https://mcp.example.invalid/mcp", auth=auth, bearer_token="t"
        )
    config = ClientCredentialsConfig(
        token_url="https://idp.example.invalid/token",
        client_id="c",
        client_secret_ref="env://S",
    )
    with pytest.raises(ValidationError, match="applies only to a url"):
        EndpointSpec(command="demo-mcp", client_credentials=config)
    with pytest.raises(ValidationError, match="at most one"):
        EndpointSpec(
            url="https://mcp.example.invalid/mcp",
            client_credentials=config,
            bearer_token="env://T",
        )
