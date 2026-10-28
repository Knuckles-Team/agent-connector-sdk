"""Declared auth schemes: refresh, 401 retry, CA bundle and redaction."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_connector_sdk.auth.declare import (
    ApiKey,
    AuthConfigurationError,
    AuthDeclaration,
    Basic,
    Bearer,
    ClientCredentials,
    ManagedClient,
    RefreshToken,
    SessionLogin,
    client_factory,
    open_client,
)
from agent_connector_sdk.auth.tokens import TokenRequestError
from agent_connector_sdk.http.errors import TlsVerificationError
from agent_connector_sdk.testing.certificates import issue_test_certificates
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

_JSON = {"Content-Type": "application/json"}
_SECRET = "s3cr3t-value"


def _tok(value: str, ttl: int = 300, refresh: str | None = None) -> ScriptedResponse:
    body: dict[str, object] = {"access_token": value, "expires_in": ttl}
    if refresh:
        body["refresh_token"] = refresh
    return ScriptedResponse(body=json.dumps(body).encode(), headers=_JSON)


def _open(
    server: ScriptedHttpServer, auth: AuthDeclaration, **kw: Any
) -> ManagedClient:
    return open_client(
        base_url=server.base_url,
        auth=auth,
        tls="demo",
        allow_plaintext=True,
        **kw,
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "TLS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_TOKEN", _SECRET)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_bearer_and_api_key_and_basic_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER", "svc")
    ok = ScriptedResponse(body=b"{}", headers=_JSON)
    with ScriptedHttpServer(ok, ok, ok, ok) as server:
        with _open(server, Bearer(env="DEMO_TOKEN")) as managed:
            managed.client.get("/a")
        with _open(
            server, ApiKey(env="DEMO_TOKEN", header="X-Api-Key", prefix="Key ")
        ) as managed:
            managed.client.get("/b")
        with _open(server, ApiKey(env="DEMO_TOKEN", query="apikey")) as managed:
            managed.client.get("/c")
        with _open(
            server, Basic(user_env="DEMO_USER", password_env="DEMO_TOKEN")
        ) as managed:
            managed.client.get("/d")
        seen = server.requests
    assert seen[0].headers["authorization"] == f"Bearer {_SECRET}"
    assert seen[1].headers["x-api-key"] == f"Key {_SECRET}"
    assert f"apikey={_SECRET}" in seen[2].path
    assert (
        base64.b64decode(seen[3].headers["authorization"][6:])
        == f"svc:{_SECRET}".encode()
    )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_static_credential_retries_once_after_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with ScriptedHttpServer(
        ScriptedResponse(status=401), ScriptedResponse(body=b"{}", headers=_JSON)
    ) as server:
        with _open(server, Bearer(env="DEMO_TOKEN")) as managed:
            monkeypatch.setenv("DEMO_TOKEN", "rotated")
            assert managed.client.get("/x").status_code == 200
        seen = server.requests
    assert [r.headers["authorization"] for r in seen] == [
        f"Bearer {_SECRET}",
        "Bearer rotated",
    ]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_unchanged_credential_is_not_retried() -> None:
    with ScriptedHttpServer(ScriptedResponse(status=401)) as server:
        with _open(server, Bearer(env="DEMO_TOKEN")) as managed:
            assert managed.client.get("/x").status_code == 401
        assert len(server.requests) == 1


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_client_credentials_refreshes_and_retries_on_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_CLIENT_SECRET", _SECRET)
    declaration = ClientCredentials(
        client_id="cid",
        secret_env="DEMO_CLIENT_SECRET",  # sanitizer:ignore - env var name, not a value
        token_url="PLACEHOLDER",
    )
    with ScriptedHttpServer() as server:
        declaration = ClientCredentials(
            client_id="cid",
            secret_env="DEMO_CLIENT_SECRET",  # sanitizer:ignore - env var name, not a value
            token_url=f"{server.base_url}/token",
        )
        server.enqueue(
            _tok("t1"),
            ScriptedResponse(status=401),
            _tok("t2"),
            ScriptedResponse(body=b"{}", headers=_JSON),
        )
        with _open(server, declaration) as managed:
            assert managed.client.get("/api").status_code == 200
        seen = server.requests
    assert [r.headers.get("authorization") for r in seen[1::2]] == [
        "Bearer t1",
        "Bearer t2",
    ]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_token_refreshed_before_expiry() -> None:
    with ScriptedHttpServer() as server:
        ok = ScriptedResponse(body=b"{}", headers=_JSON)
        server.enqueue(_tok("t1", ttl=1), ok, _tok("t2"), ok)
        declaration = ClientCredentials(
            client_id="cid",
            secret_ref="env://DEMO_TOKEN",
            token_url=f"{server.base_url}/token",
        )
        with _open(server, declaration) as managed:
            managed.client.get("/a")
            managed.client.get("/b")
        seen = server.requests
    assert [r.headers.get("authorization") for r in seen[1::2]] == [
        "Bearer t1",
        "Bearer t2",
    ]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_refresh_token_grant_rotates_the_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_REFRESH", "r1")
    with ScriptedHttpServer() as server:
        ok = ScriptedResponse(body=b"{}", headers=_JSON)
        server.enqueue(
            _tok("a1", refresh="r2"), ScriptedResponse(status=401), _tok("a2"), ok
        )
        declaration = RefreshToken(
            refresh_env="DEMO_REFRESH",
            client_id="cid",
            secret_ref="env://DEMO_TOKEN",
            token_url=f"{server.base_url}/token",
        )
        with _open(server, declaration) as managed:
            assert managed.client.get("/api").status_code == 200
        seen = server.requests
    assert (
        b"grant_type=refresh_token" in seen[0].body
        and b"refresh_token=r1" in seen[0].body
    )
    assert b"refresh_token=r2" in seen[2].body
    assert seen[3].headers["authorization"] == "Bearer a2"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_failed_token_request_is_typed_and_leaks_nothing() -> None:
    with ScriptedHttpServer(
        ScriptedResponse(status=400, body=_SECRET.encode())
    ) as server:
        declaration = ClientCredentials(
            client_id="cid",
            secret_ref="env://DEMO_TOKEN",
            token_url=f"{server.base_url}/token",
        )
        with (
            _open(server, declaration) as managed,
            pytest.raises(TokenRequestError) as info,
        ):
            managed.client.get("/api")
    assert _SECRET not in str(info.value) and _SECRET not in repr(info.value)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_session_login_reuses_cookie_and_relogs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_USER", "svc")
    ok = ScriptedResponse(body=b"{}", headers=_JSON)

    def login(sid: str) -> ScriptedResponse:
        return ScriptedResponse(headers={"Set-Cookie": f"SID={sid}; Path=/"})

    with ScriptedHttpServer(
        login("one"), ok, ok, ScriptedResponse(status=403), login("two"), ok
    ) as server:
        declaration = SessionLogin(
            login_path="/login", user_env="DEMO_USER", password_env="DEMO_TOKEN"
        )
        with _open(server, declaration) as managed:
            managed.client.get("/a")
            managed.client.get("/b")
            managed.client.get("/c")
        seen = server.requests
    assert seen[0].path == "/login" and f"password={_SECRET}".encode() in seen[0].body
    assert seen[1].headers["cookie"] == "SID=one" == seen[2].headers["cookie"]
    assert seen[5].headers["cookie"] == "SID=two"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.5")
def test_session_cookies_respect_path_and_auth_is_bound_to_origin() -> None:
    from agent_connector_sdk.auth.rotating import SessionLoginAuth
    from agent_connector_sdk.http.client import create_http_client
    from agent_connector_sdk.http.options import HttpClientOptions

    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/login":
            return httpx.Response(200, headers={"Set-Cookie": "SID=secret; Path=/api"})
        return httpx.Response(200)

    auth = SessionLoginAuth(login_path="/login", username="user", password=lambda: "pw")
    options = HttpClientOptions(base_url="https://one.example.test", auth=auth)
    with create_http_client(options, transport=httpx.MockTransport(serve)) as client:
        client.get("https://one.example.test/api/resource")
        client.get("https://one.example.test/other")
        with pytest.raises(TokenRequestError, match="origin"):
            client.get("https://two.example.test/api/resource")

    assert requests[1].headers["Cookie"] == "SID=secret"
    assert "Cookie" not in requests[2].headers
    assert len(requests) == 3


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_session_cross_origin_redirect_is_never_dispatched(
    asynchronous: bool,
) -> None:
    from agent_connector_sdk.auth.rotating import SessionLoginAuth
    from agent_connector_sdk.http.client import (
        create_async_http_client,
        create_http_client,
    )
    from agent_connector_sdk.http.options import HttpClientOptions

    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/login":
            return httpx.Response(
                200, headers={"Set-Cookie": "SID=secret; Domain=example.test; Path=/"}
            )
        return httpx.Response(302, headers={"Location": "https://two.example.test/api"})

    auth = SessionLoginAuth(login_path="/login", username="user", password=lambda: "pw")
    options = HttpClientOptions(base_url="https://one.example.test", auth=auth)
    if asynchronous:
        async with create_async_http_client(
            options, transport=httpx.MockTransport(serve)
        ) as client:
            with pytest.raises(TokenRequestError, match="origin"):
                await client.get("/api", follow_redirects=True)
    else:
        with (
            create_http_client(options, transport=httpx.MockTransport(serve)) as client,
            pytest.raises(TokenRequestError, match="origin"),
        ):
            client.get("/api", follow_redirects=True)
    assert [request.url.host for request in requests] == [
        "one.example.test",
        "one.example.test",
    ]


def test_session_auth_refuses_plain_httpx_client() -> None:
    from agent_connector_sdk.auth.rotating import SessionLoginAuth

    requests: list[httpx.Request] = []
    auth = SessionLoginAuth(login_path="/login", username="user", password=lambda: "pw")
    with (
        httpx.Client(
            auth=auth,
            transport=httpx.MockTransport(
                lambda req: requests.append(req) or httpx.Response(200)
            ),
        ) as client,
        pytest.raises(TokenRequestError, match="governed client"),
    ):
        client.get("https://one.example.test/api")
    assert requests == []


def test_session_allows_same_origin_redirect() -> None:
    from agent_connector_sdk.auth.rotating import SessionLoginAuth
    from agent_connector_sdk.http.client import create_http_client
    from agent_connector_sdk.http.options import HttpClientOptions

    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/login":
            return httpx.Response(
                200, headers={"Set-Cookie": "SID=secret; Path=/; Secure"}
            )
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/target"})
        return httpx.Response(200)

    auth = SessionLoginAuth(login_path="/login", username="user", password=lambda: "pw")
    options = HttpClientOptions(base_url="https://one.example.test", auth=auth)
    with create_http_client(options, transport=httpx.MockTransport(serve)) as client:
        assert client.get("/start", follow_redirects=True).status_code == 200
    assert requests[-1].url.path == "/target"
    assert requests[-1].headers["Cookie"] == "SID=secret"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_ca_bundle_comes_from_the_declared_tls_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    certificates = issue_test_certificates()
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text(certificates.ca_pem)
    context = certificates.server_context(tmp_path)
    ok = ScriptedResponse(body=b"{}", headers=_JSON)
    with ScriptedHttpServer(ok, ssl_context=context) as server:
        with (
            open_client(
                base_url=server.base_url, auth=Bearer(env="DEMO_TOKEN"), tls="demo"
            ) as untrusted,
            pytest.raises(TlsVerificationError),
        ):
            untrusted.client.get("/x")
        monkeypatch.setenv("DEMO_CA_BUNDLE", str(ca_file))
        with open_client(
            base_url=server.base_url, auth=Bearer(env="DEMO_TOKEN"), tls="demo"
        ) as trusted:
            assert trusted.client.get("/x").status_code == 200


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_declarations_and_errors_never_expose_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with (
        ScriptedHttpServer(ScriptedResponse(body=b"{}", headers=_JSON)) as server,
        _open(server, Bearer(env="DEMO_TOKEN")) as managed,
    ):
        managed.client.get("/x")
        assert _SECRET not in repr(managed) + repr(managed.client.auth)
    assert _SECRET not in caplog.text
    assert _SECRET not in repr(Bearer(env="DEMO_TOKEN"))


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_misdeclared_auth_fails_with_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEMO_URL", raising=False)
    with pytest.raises(AuthConfigurationError):
        client_factory(url_env="DEMO_URL", auth=Bearer(env="DEMO_TOKEN"), tls="demo")()
    monkeypatch.setenv("DEMO_URL", "http://127.0.0.1:9")
    with pytest.raises(AuthConfigurationError):
        client_factory(url_env="DEMO_URL", auth=Bearer(), tls="demo")()
    with pytest.raises(AuthConfigurationError):
        client_factory(url_env="DEMO_URL", auth=ApiKey(env="DEMO_TOKEN"), tls="demo")()


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_client_factory_builds_once_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    with ScriptedHttpServer() as server:
        monkeypatch.setenv("DEMO_URL", server.base_url)
        monkeypatch.setenv("DEMO_PLAIN", "true")
        get_client = client_factory(
            url_env="DEMO_URL",
            auth=Bearer(env="DEMO_TOKEN"),
            tls="demo",
            allow_plaintext_env="DEMO_PLAIN",
        )
        assert get_client() is get_client()
        get_client.close()  # type: ignore[attr-defined]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R028.4")
def test_no_auth_and_the_building_blocks_are_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_connector_sdk.auth.declare import BuildContext, NoAuth
    from agent_connector_sdk.auth.refresh_token import RefreshTokenProvider
    from agent_connector_sdk.auth.rotating import RotatingAuth, SessionLoginAuth

    with ScriptedHttpServer(ScriptedResponse(body=b"{}", headers=_JSON)) as server:
        declaration: AuthDeclaration = NoAuth()
        with _open(server, declaration) as managed:
            assert isinstance(managed, ManagedClient)
            managed.client.get("/x")
        assert "authorization" not in server.requests[0].headers
        context = BuildContext(server.base_url, httpx.Client(), None)
        assert declaration.build(context) is None
        context.token_client.close()
    assert "<redacted>" in repr(RotatingAuth(lambda: "v", lambda r, s: None))
    assert "<redacted>" in repr(
        SessionLoginAuth(login_path="/l", username="u", password=lambda: "p")
    )
    provider = RefreshTokenProvider(
        token_url="http://127.0.0.1:9/t",
        client_id="c",
        refresh_token_ref="env://DEMO_TOKEN",
        http_client=httpx.Client(),
    )
    assert "DEMO" not in repr(provider) or _SECRET not in repr(provider)
