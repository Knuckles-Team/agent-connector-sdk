"""SDK-CONNECTOR-CONTROL-R031: a literal client_secret, matching the prior call shape."""

from __future__ import annotations

import base64

import httpx
import pytest

from agent_connector_sdk.auth.client_credentials import ClientCredentialsTokenProvider

_LITERAL_SECRET = "s3cr3t-value"


def _minting_transport(
    captured: list[str],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("authorization", ""))
        return httpx.Response(
            200,
            json={"access_token": "minted-token", "expires_in": 300},
            request=request,
        )

    return httpx.MockTransport(handler)


def test_literal_client_secret_is_used_to_fetch_a_token() -> None:
    captured: list[str] = []
    client = httpx.Client(transport=_minting_transport(captured))
    provider = ClientCredentialsTokenProvider(
        token_url="https://issuer.example.com/token",
        client_id="fleet-client",
        client_secret=_LITERAL_SECRET,
        http_client=client,
    )

    token = provider.get_token()

    assert token == "minted-token"
    assert len(captured) == 1
    scheme, _, encoded = captured[0].partition(" ")
    assert scheme == "Basic"
    assert base64.b64decode(encoded).decode() == f"fleet-client:{_LITERAL_SECRET}"


def test_requires_exactly_one_of_ref_and_literal_secret() -> None:
    client = httpx.Client(transport=_minting_transport([]))
    with pytest.raises(ValueError):
        ClientCredentialsTokenProvider(
            token_url="https://issuer.example.com/token",
            client_id="fleet-client",
            http_client=client,
        )
    with pytest.raises(ValueError):
        ClientCredentialsTokenProvider(
            token_url="https://issuer.example.com/token",
            client_id="fleet-client",
            client_secret_ref="env://SOME_SECRET",
            client_secret=_LITERAL_SECRET,
            http_client=client,
        )


def test_literal_secret_never_appears_in_repr_or_str() -> None:
    client = httpx.Client(transport=_minting_transport([]))
    provider = ClientCredentialsTokenProvider(
        token_url="https://issuer.example.com/token",
        client_id="fleet-client",
        client_secret=_LITERAL_SECRET,
        http_client=client,
    )
    assert _LITERAL_SECRET not in repr(provider)
    assert _LITERAL_SECRET not in str(provider)
