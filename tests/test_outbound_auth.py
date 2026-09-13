"""Static, client-credentials and delegated outbound auth."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp.server.auth import AccessToken as FastMcpAccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from agent_connector_sdk.auth.client_credentials import (
    ClientCredentialsAuth,
    ClientCredentialsTokenProvider,
)
from agent_connector_sdk.auth.delegation import (
    DelegatedTokenAuth,
    DelegationSettings,
    current_user_identity,
    current_user_token,
    exchange_token,
)
from agent_connector_sdk.auth.static import (
    ApiKeyAuth,
    BearerAuth,
    api_key_auth,
    basic_auth,
    bearer_auth,
)
from agent_connector_sdk.auth.tokens import (
    AccessToken,
    TokenRequestError,
    parse_token_response,
    request_access_token,
)
from agent_connector_sdk.auth.values import header_safe, resolved_credential
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.credentials.resolver import CredentialUnavailableError
from agent_connector_sdk.exceptions import LoginRequiredError
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.errors import HttpProblemError
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

_JSON = {"Content-Type": "application/json"}
#: The verified caller access token the fixture MCP context carries.
_CALLER_JWT = "caller-jwt"


def _token(value: str, ttl: int = 300) -> ScriptedResponse:
    return ScriptedResponse(
        body=json.dumps({"access_token": value, "expires_in": ttl}).encode(),
        headers=_JSON,
    )


def _sent(
    auth: httpx.Auth, url: str = "https://api.example.invalid/x"
) -> httpx.Request:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler), auth=auth) as client:
        client.get(url)
    return seen[-1]


@pytest.fixture
def token_server() -> Iterator[ScriptedHttpServer]:
    with ScriptedHttpServer() as server:
        yield server


@pytest.fixture
def token_client(token_server: ScriptedHttpServer) -> Iterator[httpx.Client]:
    options = HttpClientOptions(
        base_url=token_server.base_url, retry=RetryPolicy(max_attempts=1)
    )
    with create_http_client(options) as client:
        yield client


def test_static_auth_from_references(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TOKEN", "t0ken")
    monkeypatch.setenv("DEMO_PASSWORD", "pa55")
    monkeypatch.setenv("DEMO_BROKEN", "line\nbreak")
    bearer = bearer_auth("env://DEMO_TOKEN")
    assert isinstance(bearer, BearerAuth) and "t0ken" not in repr(bearer)
    assert _sent(bearer).headers["authorization"] == "Bearer t0ken"
    basic = _sent(basic_auth("svc", "env://DEMO_PASSWORD")).headers["authorization"]
    assert base64.b64decode(basic.removeprefix("Basic ")) == b"svc:pa55"
    header_key = api_key_auth("env://DEMO_TOKEN", header="X-Api-Key", prefix="Key ")
    assert _sent(header_key).headers["x-api-key"] == "Key t0ken"
    query_key = api_key_auth("env://DEMO_TOKEN", query="apikey")
    assert isinstance(query_key, ApiKeyAuth) and "t0ken" not in repr(query_key)
    assert _sent(query_key).url.params["apikey"] == "t0ken"
    with pytest.raises(SecretReferenceError):
        bearer_auth("plain-token-value")
    with pytest.raises(CredentialUnavailableError):
        bearer_auth("env://DEMO_BROKEN")
    with pytest.raises(ValueError):
        ApiKeyAuth("k", header="X", query="q")
    with pytest.raises(ValueError):
        basic_auth("a:b", "env://DEMO_PASSWORD")


def test_parse_token_response() -> None:
    token = parse_token_response(b'{"access_token": "abc", "expires_in": 60}')
    assert (
        isinstance(token, AccessToken)
        and token.value == "abc"
        and token.ttl_seconds == 60
    )
    assert token.fresh(30) and not token.fresh(61) and "abc" not in repr(token)
    for body in (
        b"nope",
        b"[]",
        b'{"expires_in": 5}',
        b'{"access_token": "a", "expires_in": true}',
        b'{"access_token": "a", "expires_in": 0}',
        b'{"access_token": "a", "expires_in": 999999}',
    ):
        with pytest.raises(TokenRequestError):
            parse_token_response(body)


def test_request_access_token_failure_keeps_cause(
    token_server: ScriptedHttpServer, token_client: httpx.Client
) -> None:
    token_server.enqueue(
        ScriptedResponse(status=400, body=b'{"error": "invalid_client"}')
    )
    with pytest.raises(TokenRequestError) as raised:
        request_access_token(
            token_client, "/token", form={"grant_type": "client_credentials"}
        )
    assert isinstance(raised.value.__cause__, HttpProblemError)


def test_client_credentials_cache_refresh_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    token_server: ScriptedHttpServer,
    token_client: httpx.Client,
) -> None:
    monkeypatch.setenv("DEMO_CLIENT_SECRET", "cl1ent-secret")
    provider = ClientCredentialsTokenProvider(
        token_url="/token",
        client_id="svc",
        client_secret_ref="env://DEMO_CLIENT_SECRET",
        http_client=token_client,
        audience="api",
        scope="read",
    )
    assert provider.access_token_ttl is None
    token_server.enqueue(
        _token("first", 120), _token("second"), ScriptedResponse(status=500)
    )
    assert provider.get_token() == provider.get_token() == "first"
    assert provider.access_token_ttl == 120
    assert provider.get_token(force=True) == "second"
    form = parse_qs(token_server.requests[0].body.decode())
    assert form == {
        "grant_type": ["client_credentials"],
        "audience": ["api"],
        "scope": ["read"],
    }
    assert (
        base64.b64decode(token_server.requests[0].headers["authorization"][6:])
        == b"svc:cl1ent-secret"
    )
    with pytest.raises(TokenRequestError):
        provider.get_token(force=True)
    missing = ClientCredentialsTokenProvider(
        token_url="/token",
        client_id="svc",
        client_secret_ref="env://DEMO_UNSET_SECRET",
        http_client=token_client,
    )
    with pytest.raises(TokenRequestError, match="client secret"):
        missing.get_token()


def _api(tokens_seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        tokens_seen.append(request.headers["authorization"])
        return httpx.Response(401 if len(tokens_seen) == 1 else 200)

    return httpx.MockTransport(handler)


@pytest.fixture
def provider(
    monkeypatch: pytest.MonkeyPatch, token_client: httpx.Client
) -> ClientCredentialsTokenProvider:
    monkeypatch.setenv("DEMO_CLIENT_SECRET", "s")
    return ClientCredentialsTokenProvider(
        token_url="/token",
        client_id="svc",
        client_secret_ref="env://DEMO_CLIENT_SECRET",
        http_client=token_client,
    )


def test_client_credentials_auth_remints_once_on_401(
    provider: ClientCredentialsTokenProvider, token_server: ScriptedHttpServer
) -> None:
    token_server.enqueue(_token("old"), _token("new"))
    seen: list[str] = []
    with httpx.Client(
        transport=_api(seen), auth=ClientCredentialsAuth(provider)
    ) as client:
        assert client.get("https://api.example.invalid/x").status_code == 200
    assert seen == ["Bearer old", "Bearer new"]


async def test_client_credentials_auth_async(
    provider: ClientCredentialsTokenProvider, token_server: ScriptedHttpServer
) -> None:
    token_server.enqueue(_token("a1"), _token("a2"))
    seen: list[str] = []
    async with httpx.AsyncClient(
        transport=_api(seen), auth=ClientCredentialsAuth(provider)
    ) as client:
        assert (await client.get("https://api.example.invalid/x")).status_code == 200
    assert seen == ["Bearer a1", "Bearer a2"]


def test_delegation_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DelegationSettings.from_settings() == DelegationSettings()
    with pytest.raises(ValueError, match="OIDC_TOKEN_URL"):
        DelegationSettings(
            enabled=True, client_id="c", client_secret_ref="env://S", audience="a"
        )
    with pytest.raises(SecretReferenceError):
        DelegationSettings(
            enabled=True,
            token_endpoint="/t",
            client_id="c",
            client_secret_ref="value",
            audience="a",
        )
    for name, value in {
        "ENABLE_DELEGATION": "true",
        "OIDC_TOKEN_URL": "https://idp.example.invalid/token",
        "OIDC_CLIENT_ID": "conn",
        "OIDC_CLIENT_SECRET_REF": "openbao://apps/conn#OIDC",
        "AUDIENCE": "gitlab",
    }.items():
        monkeypatch.setenv(name, value)
    settings = DelegationSettings.from_settings()
    assert (
        settings.enabled and settings.scopes == "api" and settings.audience == "gitlab"
    )


@pytest.fixture
def caller() -> Iterator[str]:
    access = FastMcpAccessToken(
        token=_CALLER_JWT, client_id="ide", scopes=[], claims={"sub": "alice"}
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    yield "caller-jwt"
    auth_context_var.reset(reset)


def test_current_user_without_and_with_verified_token(caller: str) -> None:
    assert current_user_token() == caller
    identity = current_user_identity()
    assert (
        identity is not None
        and identity.startswith("delegated-actor:")
        and "alice" not in identity
    )


def test_current_user_absent() -> None:
    assert current_user_token() is None and current_user_identity() is None


def _delegation(token_server: ScriptedHttpServer) -> DelegationSettings:
    return DelegationSettings(
        enabled=True,
        token_endpoint="/token",
        client_id="conn",
        client_secret_ref="env://DEMO_OIDC_SECRET",
        audience="gitlab",
    )


def test_exchange_token(
    monkeypatch: pytest.MonkeyPatch,
    token_server: ScriptedHttpServer,
    token_client: httpx.Client,
) -> None:
    monkeypatch.setenv("DEMO_OIDC_SECRET", "oidc")
    with pytest.raises(TokenRequestError, match="not enabled"):
        exchange_token(
            DelegationSettings(), subject_token="s", http_client=token_client
        )
    token_server.enqueue(_token("downstream"))
    exchanged = exchange_token(
        _delegation(token_server), subject_token="caller-jwt", http_client=token_client
    )
    assert exchanged.value == "downstream"
    form = parse_qs(token_server.requests[0].body.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:token-exchange"]
    assert form["subject_token"] == ["caller-jwt"] and form["audience"] == ["gitlab"]
    monkeypatch.delenv("DEMO_OIDC_SECRET")
    with pytest.raises(TokenRequestError, match="secret"):
        exchange_token(
            _delegation(token_server),
            subject_token="caller-jwt",
            http_client=token_client,
        )


def test_delegated_auth_requires_a_caller(
    token_server: ScriptedHttpServer, token_client: httpx.Client
) -> None:
    auth = DelegatedTokenAuth(_delegation(token_server), http_client=token_client)
    with pytest.raises(LoginRequiredError):
        _sent(auth)


async def test_delegated_auth_caches_per_caller(
    monkeypatch: pytest.MonkeyPatch,
    caller: str,
    token_server: ScriptedHttpServer,
    token_client: httpx.Client,
) -> None:
    monkeypatch.setenv("DEMO_OIDC_SECRET", "oidc")
    token_server.enqueue(_token("downstream"))
    auth = DelegatedTokenAuth(_delegation(token_server), http_client=token_client)
    assert _sent(auth).headers["authorization"] == "Bearer downstream"
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=auth
    ) as client:
        await client.get("https://api.example.invalid/x")
    assert seen == ["Bearer downstream"] and len(token_server.requests) == 1


def test_credential_value_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    assert header_safe("value", what="token") == "value"
    for bad in ("", "a\r\nb", "nul\x00"):
        with pytest.raises(ValueError):
            header_safe(bad, what="token")
    monkeypatch.setenv("DEMO_VALUE", "v4lue")
    assert resolved_credential("env://DEMO_VALUE", None) == "v4lue"
