"""TLS selectors can use caller-provided configuration without process mutation."""

from __future__ import annotations

import json
import os

import pytest

from scion_sdk.tls.errors import TransportSecurityError
from scion_sdk.tls.resolve import resolve_tls_profile


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.13")
def test_explicit_tls_settings_are_isolated_from_process(monkeypatch):
    monkeypatch.setenv("TLS_SYSTEM_TRUST", "false")
    monkeypatch.setenv("TLS_TRUST_ENV", "true")
    profile = resolve_tls_profile(
        "demo", settings={"TLS_SYSTEM_TRUST": "true", "TLS_TRUST_ENV": "false"}
    )
    assert profile.system_trust is True
    assert profile.trust_env is False
    assert profile.verify_enabled
    assert resolve_tls_profile("demo", settings={}).system_trust is True
    assert os.environ["TLS_SYSTEM_TRUST"] == "false"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.13")
def test_explicit_tls_settings_select_service_profile_and_refuse_missing():
    config = {
        "DEMO_TLS_PROFILE": "custom",
        "TLS_PROFILES": json.dumps({"profiles": {"custom": {"trust_env": False}}}),
    }
    selected = resolve_tls_profile("demo", settings=config)
    assert selected.name == "custom"
    assert selected.source == "runtime_catalog"
    assert selected.trust_env is False
    with pytest.raises(TransportSecurityError, match="tls_profile_not_found"):
        resolve_tls_profile("other", profile_name="missing", settings=config)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.13")
def test_explicit_tls_settings_refuse_non_string_values():
    with pytest.raises(TransportSecurityError, match="tls_setting_invalid"):
        resolve_tls_profile("demo", settings={"TLS_TRUST_ENV": False})


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.13")
def test_explicit_settings_delegate_secret_reference_to_resolver(monkeypatch):
    monkeypatch.setenv("TLS_PROFILES_REF", "env://UNTRUSTED_PROCESS_VALUE")
    calls = []

    class Resolver:
        def resolve(self, reference):
            calls.append(reference.render())
            return json.dumps({"profiles": {"chosen": {"trust_env": False}}})

    selected = resolve_tls_profile(
        "demo",
        settings={"TLS_PROFILE": "chosen", "TLS_PROFILES_REF": "env://CALLER_PROFILE"},
        resolver=Resolver(),
    )
    assert calls == ["env://CALLER_PROFILE"]
    assert selected.source == "secret_catalog"
    assert selected.trust_env is False
