"""SDK-CONNECTOR-CONTROL-R014.10-R014.14: the remaining connector runtime moved from agent-utilities."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import stat
import time

import httpx
import pytest

from agent_connector_sdk.auth.browser import (
    BaseBrowserAuthManager,
    FileTokenStore,
    generate_pkce,
)
from agent_connector_sdk.contracts import (
    CONNECTOR_UNCONFIGURED_MARKING,
    ExternalAccess,
    default_external_access,
)
from agent_connector_sdk.exceptions import ApiError, AuthError, ParameterError
from agent_connector_sdk.http.support import (
    AuthHeaderInjector,
    BaseApiClient,
    BasicAuth,
    DestructiveOperationError,
    QueryApiKeyAuth,
    TokenAuth,
)
from agent_connector_sdk.mcp import env_drift
from agent_connector_sdk.mcp.graphql import (
    ctx_graphql_get_type_details,
    ctx_graphql_list_types,
)


def _client(handler, **kwargs) -> BaseApiClient:
    return BaseApiClient(
        "https://api.example.test/api",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.10")
def test_r014_10_token_auth_envelope_and_error_mapping():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/missing"):
            return httpx.Response(404, json={"message": "no s3cret-token here"})
        return httpx.Response(
            200, json={"ok": True}, headers={"X-RateLimit-Remaining": "9"}
        )

    auth = TokenAuth("s3cret-token", header="X-API-Key", prefix=None)
    with _client(handler, auth=auth) as client:
        envelope = client.get("stacks", params={"a": 1, "skip": None})
        assert envelope["status_code"] == 200
        assert envelope["data"] == {"ok": True}
        assert envelope["rate_limit"]["remaining"] == 9
        assert seen[0].headers["X-API-Key"] == "s3cret-token"
        assert str(seen[0].url) == "https://api.example.test/api/stacks?a=1"
        with pytest.raises(ParameterError) as raised:
            client.get("missing")
        assert "s3cret-token" not in str(raised.value)
        error = client.get("missing", raise_for_status=False)
        assert error["status_code"] == 404
        with pytest.raises(DestructiveOperationError):
            client.guard_destructive("delete stack")


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.10")
def test_r014_10_auth_strategies_and_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    assert AuthHeaderInjector().headers() == {}
    assert TokenAuth(token_provider=lambda: "t").headers() == {
        "Authorization": "Bearer t"
    }
    with pytest.raises(ValueError):
        TokenAuth()
    basic = BasicAuth("u", "p").headers()["Authorization"]
    assert basic == "Basic " + base64.b64encode(b"u:p").decode()
    assert QueryApiKeyAuth("key", "k").params() == {"key": "k"}

    calls = {"n": 0}

    def limited(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(204)

    with _client(limited) as client:
        assert client.post("x", json={})["status_code"] == 204
    assert calls["n"] == 3

    class Refreshing(TokenAuth):
        invalidated = 0

        def invalidate(self) -> None:
            Refreshing.invalidated += 1

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "denied"})

    with (
        _client(unauthorized, auth=Refreshing("t")) as client,
        pytest.raises(AuthError),
    ):
        client.get("x")
    assert Refreshing.invalidated == 1

    with (
        _client(lambda r: httpx.Response(500, text="boom")) as client,
        pytest.raises(ApiError),
    ):
        client.delete("x")
    with pytest.raises(ValueError):
        BaseApiClient("https://x.test", verify=False)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.11")
def test_r014_11_browser_auth_pkce_store_and_refresh(tmp_path, monkeypatch):
    verifier, challenge = generate_pkce()
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).decode().rstrip("=")

    store = FileTokenStore(tmp_path / "tokens")
    manager = BaseBrowserAuthManager(
        client_id="c",
        auth_endpoint="https://idp.test/authorize",
        token_endpoint="https://idp.test/token",
        scopes="openid",
        secret_key="leanix/oauth_tokens/host",
        secrets_client=store,
    )
    assert manager.resolve_credentials() is None
    manager.save_tokens(
        {"access_token": "old", "refresh_token": "r", "expires_at": 0.0}
    )
    saved = next((tmp_path / "tokens").iterdir())
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600

    def fake_post(url, **kwargs):
        assert kwargs["data"]["grant_type"] == "refresh_token"
        return httpx.Response(
            200,
            json={"access_token": "new", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert manager.resolve_credentials() == "new"
    assert json.loads(store.get("leanix/oauth_tokens/host"))["refresh_token"] == "r"
    assert "code_challenge_method=S256" in manager._build_authorization_url(
        "https://idp.test/authorize", challenge
    )

    monkeypatch.setenv("LEANIX_API_KEY_TEST", "direct")
    keyed = BaseBrowserAuthManager(
        client_id="c",
        auth_endpoint="a",
        token_endpoint="t",
        scopes="s",
        secret_key="k",
        secrets_client=store,
        api_key_env_var="LEANIX_API_KEY_TEST",
    )
    assert keyed.resolve_credentials() == "direct"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.12")
def test_r014_12_graphql_helpers_sync_async_and_failure():
    async def run():
        async def execute_async(query, variables=None):
            return {"query": query, "variables": variables}

        def execute_sync(query, variables=None):
            return {"data": {"__schema": {"types": [{"name": "Query"}]}}}

        def broken(query, variables=None):
            raise RuntimeError("secret-detail")

        listed = await ctx_graphql_list_types(execute_sync)
        detail = await ctx_graphql_get_type_details(execute_async, "Issue")
        failure = await ctx_graphql_list_types(broken)
        return listed, detail, failure

    listed, detail, failure = asyncio.run(run())
    assert listed["data"]["__schema"]["types"][0]["name"] == "Query"
    assert detail["variables"] == {"name": "Issue"}
    assert "__type(name: $name)" in detail["query"]
    assert failure["code"] == "operation_failed"
    assert failure["error_class"] == "RuntimeError"
    assert "secret-detail" not in json.dumps(failure)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.13")
def test_r014_13_external_access_descriptor():
    access = ExternalAccess(read_roles=["kg:read"])
    assert access.model_dump() == {
        "is_public": False,
        "user_emails": [],
        "group_ids": [],
        "read_roles": ["kg:read"],
        "markings": [],
    }
    assert ExternalAccess.public().is_public is True
    assert default_external_access().markings == [CONNECTOR_UNCONFIGURED_MARKING]
    assert default_external_access().is_public is False
    with pytest.raises(ValueError):
        ExternalAccess(unknown=True)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.14")
def test_r014_14_env_drift_against_declarations(tmp_path, capsys):
    pkg = tmp_path / "demo_connector"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "server.py").write_text(
        "import os\n"
        "from agent_connector_sdk.config import setting\n"
        "TOKEN_VAR = 'DEMO_TOKEN'\n"
        "URL = setting('DEMO_URL')\n"
        "TOKEN = os.environ.get(TOKEN_VAR)\n"
        "os.environ['DEMO_WRITTEN'] = '1'\n"
        "def register_widget_tools(mcp):\n"
        "    return mcp\n"
        "def _limit(group, suffix):\n"
        "    return setting(f'{group}_{suffix}')\n"
        "_limit.dynamic_env_prefix_arg = 'group'\n"
        "_limit.dynamic_env_suffixes = ('MAX_ITEMS',)\n"
        "LIMIT = _limit('demo', 'MAX_ITEMS')\n"
    )
    (tmp_path / ".env.example").write_text(
        "DEMO_URL=https://demo\n# DEMO_TOKEN=\nDEMO_STALE=1\nTRANSPORT=stdio\n"
    )
    (tmp_path / "mcp_config.json").write_text(
        json.dumps({"mcpServers": {"demo": {"env": {"DEMO_OLD": "x"}}}})
    )
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "mcp.compose.yml").write_text(
        "services:\n  demo:\n    image: ${DEMO_IMAGE:-demo}\n"
        "    environment:\n      - DEMO_URL=${DEMO_URL}\n"
    )
    report = env_drift.analyze(tmp_path)
    found = {(f["type"], f["var"]) for f in report["findings"]}
    assert found == {
        ("DEAD", "DEMO_STALE"),
        ("DEAD", "DEMO_OLD"),
        ("UNDOCUMENTED", "WIDGETTOOL"),
        ("UNDOCUMENTED", "DEMO_MAX_ITEMS"),
        ("UNDOCUMENTED", "DEMO_IMAGE"),
    }
    assert report["drift"] == 5
    assert env_drift.main([str(tmp_path), "--check"]) == 1
    assert "[DEAD] DEMO_STALE" in capsys.readouterr().out
    assert env_drift._format is env_drift.format_report
    assert "AGENT_UTILITIES" not in " ".join(env_drift.framework_reads())
