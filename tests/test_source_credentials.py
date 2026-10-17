"""Source credentials: typed material by source name, resolved from references only."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from agent_connector_sdk.credentials.references import SecretReference
from agent_connector_sdk.credentials.source import (
    CREDENTIAL_TYPES,
    ApiKeyCredential,
    AuthMaterial,
    BasicAuthCredential,
    CookieSessionCredential,
    KeylessCredential,
    OAuth2Credential,
    SourceCredential,
    SourceCredentials,
    build_credential,
)

SECRETS = {
    "API": "k-1",
    "COOKIES": "auth_token=a; ct0=b",
    "PASSWORD": "pw",
    "TOKEN": '{"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 60}',
    "CLIENT": "cs",
}


class _Resolver:
    def resolve(self, reference: SecretReference) -> str:
        return SECRETS[reference.target]


@pytest.mark.parametrize(
    ("descriptor", "headers", "params"),
    [
        ({"type": "none"}, {}, {}),
        (
            {"type": "api_key", "secret": "env://API"},
            {"Authorization": "Bearer k-1"},
            {},
        ),
        (
            {
                "type": "api_key",
                "secret": "env://API",
                "placement": "query",
                "name": "key",
                "prefix": "",
            },
            {},
            {"key": "k-1"},
        ),
        (
            {"type": "cookie_session", "secret": "env://COOKIES"},
            {"Cookie": "auth_token=a; ct0=b"},
            {},
        ),
        (
            {"type": "basic", "username": "u", "password_secret": "env://PASSWORD"},
            {"Authorization": "Basic " + base64.b64encode(b"u:pw").decode()},
            {},
        ),
    ],
)
def test_descriptor_materializes_request_auth(
    descriptor: dict[str, Any], headers: dict[str, str], params: dict[str, str]
) -> None:
    material = build_credential(descriptor, _Resolver()).materialize()
    assert (material.headers, material.params) == (headers, params)


@pytest.mark.parametrize(
    "descriptor",
    [
        {"type": "api_key", "secret": "literal-key"},
        {"type": "api_key", "secret": "vault://legacy/path"},
        {"type": "cookie_session", "cookies": {"a": "b"}},
        {"type": "oauth2", "refresh_token": "inline"},
        {"type": "oauth2", "secret": "env://TOKEN", "verify": False},
    ],
)
def test_inline_material_and_non_reference_secrets_are_refused(
    descriptor: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        build_credential(descriptor, _Resolver())


def test_unknown_type_is_a_key_error_naming_the_kinds() -> None:
    with pytest.raises(KeyError, match="api_key"):
        build_credential({"type": "kerberos"})


def test_oauth2_refreshes_inside_the_expiry_skew_with_an_injected_clock() -> None:
    now = [0.0]
    posts: list[dict[str, str]] = []

    def post(url: str, form: dict[str, str], auth: Any) -> dict[str, Any]:
        posts.append(form)
        return {"access_token": f"at-{len(posts) + 1}", "expires_in": 60}

    credential = OAuth2Credential(
        "at-1",
        "rt-1",
        token_url="https://idp.example.test/token",
        client_id="c",
        client_secret="cs",
        expires_in=60,
        post=post,
        clock=lambda: now[0],
    )
    assert credential.materialize().headers == {"Authorization": "Bearer at-1"}
    now[0] = 31.0
    assert credential.materialize().headers == {"Authorization": "Bearer at-2"}
    assert posts == [
        {"grant_type": "refresh_token", "refresh_token": "rt-1", "client_id": "c"}
    ]


def test_oauth2_failed_refresh_sends_no_header() -> None:
    def post(*_: Any) -> dict[str, Any]:
        raise ConnectionError("down")

    credential = OAuth2Credential(
        None, "rt", token_url="https://t", client_id="c", post=post
    )
    assert credential.materialize().headers == {}
    assert credential.is_present()


def test_registry_caches_degrades_and_reports_status_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SOURCE_CREDENTIALS", '{"github": {"type": "api_key", "secret": "env://API"}}'
    )
    registry = SourceCredentials(resolver=_Resolver())
    registry.register("broken", {"type": "kerberos"})
    assert registry.get("github") is registry.get("github")
    assert registry.available("github") is True
    assert (
        registry.available("broken") is False and registry.available("keyless") is False
    )
    status = registry.status()
    assert status == {
        "broken": {"type": "none", "available": False},
        "github": {"type": "api_key", "available": True},
    }
    assert "k-1" not in repr(status)
    monkeypatch.setenv("SOURCE_CREDENTIALS", "not json")
    assert SourceCredentials(resolver=_Resolver()).status() == {}


def test_registered_kinds_and_material_merge() -> None:
    assert {
        "none": KeylessCredential,
        "api_key": ApiKeyCredential,
        "cookie_session": CookieSessionCredential,
        "basic": BasicAuthCredential,
        "oauth2": OAuth2Credential,
    } == CREDENTIAL_TYPES
    assert all(issubclass(kind, SourceCredential) for kind in CREDENTIAL_TYPES.values())
    material = AuthMaterial(headers={"A": "new"}, params={"p": "1"})
    assert material.merged_into({"A": "old", "B": "kept"}) == (
        {"A": "new", "B": "kept"},
        {"p": "1"},
        {},
    )
