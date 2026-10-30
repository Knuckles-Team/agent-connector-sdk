"""Loopback browser callbacks accept only the state sent by the login."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from scion_sdk.auth.browser import BaseBrowserAuthManager


def manager() -> BaseBrowserAuthManager:
    return BaseBrowserAuthManager(
        client_id="client",
        auth_endpoint="https://idp.example/authorize",
        token_endpoint="https://idp.example/token",
        scopes="openid",
        secret_key="token",
        redirect_port=0,
        extra_auth_params={"state": "override"},
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R046.7")
@pytest.mark.parametrize(
    ("query", "status", "expected"),
    [
        ("code=accepted&state=expected", 200, "accepted"),
        ("code=rejected&state=wrong", 400, None),
        ("code=rejected", 400, None),
        ("code=rejected&state=expected&state=other", 400, None),
        ("code=first&code=second&state=expected", 400, None),
        ("code=rejected&state=%C3%A9", 400, None),
    ],
)
def test_loopback_callback_requires_exact_state(
    query: str, status: int, expected: str | None
) -> None:
    auth = manager()
    url = auth._build_authorization_url(auth.auth_endpoint, "challenge", "expected")
    assert parse_qs(urlsplit(url).query)["state"] == ["expected"]
    server = auth._start_loopback_server("expected")
    assert server is not None
    try:
        port = server.server_address[1]
        response = httpx.get(
            f"http://127.0.0.1:{port}/callback?{query}", trust_env=False
        )
        assert response.status_code == status
        assert server.auth_code == expected
    finally:
        server.server_close()
