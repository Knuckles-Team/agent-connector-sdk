"""SDK-CONNECTOR-CONTROL-R035: a connector-scoped CredentialProvider."""

from __future__ import annotations

import logging

import pytest

from agent_connector_sdk.credentials.provider import (
    CredentialProvider,
    CredentialScopeError,
)
from agent_connector_sdk.credentials.references import parse_secret_reference


class _StubResolver:
    def resolve(self, reference: object) -> str:
        return "s3cr3t-value"


def test_resolves_env_and_in_scope_openbao_reference() -> None:
    provider = CredentialProvider(resolver=_StubResolver(), connector="freshrss-agent")
    env_ref = parse_secret_reference("env://FRESHRSS_TOKEN")
    assert provider.get_secret(env_ref) == "s3cr3t-value"

    bao_ref = parse_secret_reference("openbao://apps/freshrss-agent#TOKEN")
    assert provider.get_secret(bao_ref) == "s3cr3t-value"


def test_out_of_scope_openbao_reference_denied() -> None:
    provider = CredentialProvider(resolver=_StubResolver(), connector="freshrss-agent")
    other_ref = parse_secret_reference("openbao://apps/other-connector#TOKEN")
    with pytest.raises(CredentialScopeError):
        provider.get_secret(other_ref)


def test_resolved_value_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    provider = CredentialProvider(resolver=_StubResolver(), connector="freshrss-agent")
    with caplog.at_level(logging.DEBUG):
        value = provider.get_secret(parse_secret_reference("env://FRESHRSS_TOKEN"))
    assert value == "s3cr3t-value"
    assert "s3cr3t-value" not in caplog.text
