"""Secret references and their resolvers."""

from __future__ import annotations

import argparse

import httpx
import pytest

from agent_connector_sdk.credentials.openbao import OpenBaoCredentialResolver
from agent_connector_sdk.credentials.references import (
    SecretReference,
    SecretReferenceError,
    parse_secret_reference,
)
from agent_connector_sdk.credentials.resolution import (
    SecretReferenceAction,
    default_credential_resolver,
    resolve_secret_reference,
)
from agent_connector_sdk.credentials.resolver import (
    CompositeCredentialResolver,
    CredentialResolver,
    CredentialUnavailableError,
    EnvironmentCredentialResolver,
)


def _openbao_client(requests: list[httpx.Request], status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"data": {"data": {"TOKEN": "s3cret"}}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_references() -> None:
    env = parse_secret_reference("env://DEMO_TOKEN")
    assert env == SecretReference(scheme="env", target="DEMO_TOKEN")
    bao = parse_secret_reference("openbao://apps/freshrss-agent#TOKEN@3")
    assert (bao.mount, bao.path, bao.field, bao.version) == (
        "apps",
        "freshrss-agent",
        "TOKEN",
        3,
    )
    assert bao.render() == "openbao://apps/freshrss-agent#TOKEN@3"


@pytest.mark.parametrize(
    "reference",
    [
        "vault://apps/x#f",
        "openbao://apps/../x#f",
        "env://has space",
        "env://1BAD",
        "",
        "openbao://apps/x",
    ],
)
def test_parse_rejects_malformed_references(reference: str) -> None:
    with pytest.raises(SecretReferenceError):
        parse_secret_reference(reference)


def test_environment_and_composite_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TOKEN", "value")
    resolver: CredentialResolver = EnvironmentCredentialResolver()
    assert resolver.resolve(parse_secret_reference("env://DEMO_TOKEN")) == "value"
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(parse_secret_reference("env://DEMO_MISSING"))
    composite = CompositeCredentialResolver({"env": resolver})
    with pytest.raises(CredentialUnavailableError, match="openbao"):
        composite.resolve(parse_secret_reference("openbao://apps/x#f"))


def test_openbao_reads_kv2_field_with_version() -> None:
    requests: list[httpx.Request] = []
    resolver = OpenBaoCredentialResolver(
        "https://bao.example.invalid",
        "token",
        namespace="ns",
        http_client=_openbao_client(requests),
    )
    value = resolver.resolve(
        parse_secret_reference("openbao://apps/freshrss-agent#TOKEN@2")
    )
    assert value == "s3cret"
    assert requests[0].url.path == "/v1/apps/data/freshrss-agent"
    assert requests[0].url.params["version"] == "2"
    assert requests[0].headers["X-Vault-Token"] == "token"
    assert requests[0].headers["X-Vault-Namespace"] == "ns"
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(
            parse_secret_reference("openbao://apps/freshrss-agent#MISSING")
        )


def test_openbao_fails_closed() -> None:
    denied = OpenBaoCredentialResolver(
        "http://127.0.0.1:8200", "token", http_client=_openbao_client([], status=403)
    )
    with pytest.raises(CredentialUnavailableError):
        denied.resolve(parse_secret_reference("openbao://apps/x#TOKEN"))
    with pytest.raises(ValueError, match="HTTPS"):
        OpenBaoCredentialResolver("http://bao.example.invalid", "token")
    with pytest.raises(ValueError):
        OpenBaoCredentialResolver("https://bao.example.invalid", "")


def test_openbao_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENBAO_ADDR", raising=False)
    assert OpenBaoCredentialResolver.from_settings() is None
    monkeypatch.setenv("OPENBAO_ADDR", "https://bao.example.invalid")
    monkeypatch.setenv("OPENBAO_TOKEN_REF", "openbao://apps/bao#token")
    with pytest.raises(SecretReferenceError):
        OpenBaoCredentialResolver.from_settings()
    monkeypatch.setenv("OPENBAO_TOKEN_REF", "env://BAO_TOKEN")
    monkeypatch.setenv("BAO_TOKEN", "t")
    resolver = default_credential_resolver(http_client=_openbao_client([]))
    assert resolve_secret_reference("openbao://apps/x#TOKEN", resolver) == "s3cret"


def test_resolution_bounds_values() -> None:
    class NulResolver:
        def resolve(self, reference: SecretReference) -> str:
            return "a\x00b"

    with pytest.raises(CredentialUnavailableError):
        resolve_secret_reference("env://DEMO_NUL", NulResolver())


def test_secret_reference_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TOKEN", "resolved")
    parser = argparse.ArgumentParser(exit_on_error=False)
    parser.add_argument(
        "--token-ref",
        dest="token",
        action=SecretReferenceAction,
        resolver=EnvironmentCredentialResolver(),
    )
    assert parser.parse_args(["--token-ref", "env://DEMO_TOKEN"]).token == "resolved"
    with pytest.raises(argparse.ArgumentError):
        parser.parse_args(["--token-ref", "plaintext-secret"])
