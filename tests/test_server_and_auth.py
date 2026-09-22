"""The server factory, command line, network exposure and authentication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp.server.auth import OAuthProxy, RemoteAuthProvider, TokenVerifier
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from starlette.testclient import TestClient

from agent_connector_sdk.credentials.resolver import EnvironmentCredentialResolver
from agent_connector_sdk.mcp.auth.factory import configure_auth
from agent_connector_sdk.mcp.auth.jwt import configure_jwt_auth
from agent_connector_sdk.mcp.auth.policy import (
    AUTH_TYPES,
    AuthConfigurationError,
    AuthInputs,
    allowed_redirect_uris,
    discover_jwks_uri,
    resolve_auth_secret,
    secure_auth_url,
)
from agent_connector_sdk.mcp.auth.proxies import (
    configure_oauth_proxy,
    configure_oidc_proxy,
    configure_remote_oauth,
)
from agent_connector_sdk.mcp.auth.static import (
    configure_static_auth,
    validated_static_tokens,
)
from agent_connector_sdk.mcp.auth.verifiers import (
    any_realm_verifier,
    claims_are_current,
    hardened_jwt_verifier,
)
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.mcp.parser import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    TRANSPORTS,
    create_mcp_parser,
)
from agent_connector_sdk.mcp.server import create_mcp_server

ISSUER = "https://issuer.example.invalid"
TOKEN = "t" * 40


def _args(*argv: str) -> argparse.Namespace:
    return create_mcp_parser().parse_known_args(list(argv))[0]


def test_parser_defaults_and_choices() -> None:
    args = _args()
    assert (args.transport, args.host, args.port) == (
        "stdio",
        DEFAULT_HOST,
        DEFAULT_PORT,
    )
    assert set(AUTH_TYPES) >= {"none", "jwt"} and "sse" in TRANSPORTS
    with pytest.raises(ValueError):
        create_mcp_parser(transport_choices=("carrier-pigeon",))


def test_create_mcp_server_serves_health_and_content(package_root: Path) -> None:
    content = ConnectorContent(
        connector="demo-agent", package_root=package_root, package_version="1.0.0"
    )
    args, mcp, middlewares = create_mcp_server(
        "demo-mcp", version="1.0.0", command_args=[], content=content
    )
    assert args.transport == "stdio" and len(middlewares) == 2
    with TestClient(mcp.http_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_create_mcp_server_exits_on_unsafe_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as helped:
        create_mcp_server("demo", version="1", command_args=["--help"])
    assert helped.value.code == 0
    with pytest.raises(SystemExit):
        create_mcp_server("demo", version="1", command_args=["--port", "70000"])
    with pytest.raises(SystemExit) as exposed:
        create_mcp_server(
            "demo",
            version="1",
            command_args=["-t", "streamable-http", "-H", "10.20.30.40"],
        )
    assert exposed.value.code == 1
    capsys.readouterr()


def test_url_policy_and_redirects() -> None:
    assert secure_auth_url("http://localhost:8080/cb", field="f")
    for bad in (
        "http://example.invalid",
        "ftp://x",
        "https://user@x",
        "https://x#frag",
    ):
        with pytest.raises(AuthConfigurationError):
            secure_auth_url(bad, field="f")
    args = _args("--allowed-client-redirect-uris", "https://a.example.invalid/cb")
    assert allowed_redirect_uris(args) == ["https://a.example.invalid/cb"]
    assert allowed_redirect_uris(_args()) is None


def test_discover_jwks_uri() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/openid-configuration"
        return httpx.Response(200, json={"jwks_uri": f"{ISSUER}/jwks"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert discover_jwks_uri(ISSUER, http_client=client) == f"{ISSUER}/jwks"
    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(AuthConfigurationError):
        discover_jwks_uri(ISSUER, http_client=failing)


def test_claims_are_current() -> None:
    assert claims_are_current({"exp": 200, "iat": 100}, 150)
    assert not claims_are_current({"exp": 100}, 150)
    assert not claims_are_current({"exp": True}, 0)
    assert not claims_are_current({"exp": 500, "nbf": 400}, 100)


async def test_static_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DEMO_STATIC_TOKENS",
        json.dumps({TOKEN: {"client_id": "svc", "scopes": ["read"]}}),
    )
    inputs = AuthInputs(
        args=_args(
            "--auth-type", "static", "--static-tokens-ref", "env://DEMO_STATIC_TOKENS"
        )
    )
    verifier = configure_static_auth(inputs)
    assert (await verifier.verify_token(TOKEN)).client_id == "svc"
    assert await verifier.verify_token("x" * 40) is None
    with pytest.raises(AuthConfigurationError):
        configure_static_auth(AuthInputs(args=_args("--auth-type", "static")))
    for raw in (
        "[]",
        "{}",
        json.dumps({"short": {"client_id": "a"}}),
        json.dumps({TOKEN: {"client_id": "a", "expires_at": "soon"}}),
    ):
        with pytest.raises(AuthConfigurationError):
            validated_static_tokens(raw)
    assert resolve_auth_secret(
        "env://DEMO_STATIC_TOKENS", inputs, what="tokens"
    ).startswith("{")
    with pytest.raises(AuthConfigurationError):
        resolve_auth_secret("env://DEMO_UNSET_REF", inputs, what="tokens")


async def test_jwt_auth_single_realm_with_public_key() -> None:
    keys = RSAKeyPair.generate()
    args = _args(
        "--auth-type",
        "jwt",
        "--token-issuer",
        ISSUER,
        "--token-audience",
        "demo",
        "--token-public-key",
        keys.public_key,
    )
    verifier = configure_auth(args)
    token = keys.create_token(subject="svc", issuer=ISSUER, audience="demo")
    assert (await verifier.verify_token(token)).client_id == "svc"
    assert await verifier.verify_token("x" * 20_000) is None
    wrapped = configure_jwt_auth(
        AuthInputs(
            args=_args(
                *vars_to_argv(args), "--public-base-url", "https://mcp.example.invalid"
            )
        )
    )
    assert isinstance(wrapped, RemoteAuthProvider)


def vars_to_argv(args: argparse.Namespace) -> list[str]:
    return [
        "--token-issuer",
        args.token_issuer,
        "--token-audience",
        args.token_audience,
        "--token-public-key",
        args.token_public_key,
    ]


async def test_jwt_auth_hmac_and_multi_realm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_HMAC", "k" * 48)
    hmac_args = _args(
        "--token-issuer",
        ISSUER,
        "--token-audience",
        "demo",
        "--token-algorithm",
        "HS256",
        "--token-secret-ref",
        "env://DEMO_HMAC",
    )
    assert isinstance(
        configure_jwt_auth(
            AuthInputs(args=hmac_args, resolver=EnvironmentCredentialResolver())
        ),
        TokenVerifier,
    )
    monkeypatch.setenv("DEMO_HMAC", "short")
    with pytest.raises(AuthConfigurationError):
        configure_jwt_auth(AuthInputs(args=hmac_args))
    realms = _args(
        "--token-issuer",
        f"{ISSUER}/a,{ISSUER}/b",
        "--token-audience",
        "demo",
        "--token-jwks-uri",
        f"{ISSUER}/a/jwks,{ISSUER}/b/jwks",
    )
    assert isinstance(configure_jwt_auth(AuthInputs(args=realms)), TokenVerifier)
    misaligned = _args(
        "--token-issuer",
        f"{ISSUER}/a,{ISSUER}/b",
        "--token-audience",
        "demo",
        "--token-jwks-uri",
        f"{ISSUER}/a/jwks",
    )
    with pytest.raises(AuthConfigurationError):
        configure_jwt_auth(AuthInputs(args=misaligned))
    with pytest.raises(AuthConfigurationError):
        configure_jwt_auth(AuthInputs(args=_args("--token-audience", "demo")))


async def test_any_realm_verifier_and_hardened_verifier() -> None:
    class Fixed:
        def __init__(self, value: Any) -> None:
            self.value = value

        async def verify_token(self, token: str) -> Any:
            return self.value

    verifier = any_realm_verifier([Fixed(None), Fixed("ok")], required_scopes=None)
    assert await verifier.verify_token("x") == "ok"
    assert (
        await hardened_jwt_verifier(
            public_key=RSAKeyPair.generate().public_key
        ).verify_token("")
        is None
    )


def test_proxy_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_CLIENT_SECRET", "secret-value")
    oauth = _args(
        "--oauth-upstream-auth-endpoint",
        f"{ISSUER}/authorize",
        "--oauth-upstream-token-endpoint",
        f"{ISSUER}/token",
        "--oauth-upstream-client-id",
        "demo",
        "--oauth-upstream-client-secret-ref",
        "env://DEMO_CLIENT_SECRET",
        "--oauth-base-url",
        "https://mcp.example.invalid",
        "--token-jwks-uri",
        f"{ISSUER}/jwks",
        "--token-issuer",
        ISSUER,
        "--token-audience",
        "demo",
    )
    assert isinstance(configure_oauth_proxy(AuthInputs(args=oauth)), OAuthProxy)
    remote = _args(
        "--remote-auth-servers",
        ISSUER,
        "--remote-base-url",
        "https://mcp.example.invalid",
        "--token-jwks-uri",
        f"{ISSUER}/jwks",
        "--token-issuer",
        ISSUER,
        "--token-audience",
        "demo",
    )
    assert isinstance(
        configure_remote_oauth(AuthInputs(args=remote)), RemoteAuthProvider
    )
    with pytest.raises(AuthConfigurationError, match="oidc_config_url"):
        configure_oidc_proxy(AuthInputs(args=_args()))
    with pytest.raises(AuthConfigurationError):
        configure_auth(argparse.Namespace(auth_type="kerberos"))
    assert configure_auth(_args()) is None
