"""SCION-CONNECTOR-CONTROL-R014.18-R014.20: served security, provider profiles, plugin groups."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.shared.exceptions import MCPError

from scion_sdk.credentials import provider_profile as pp
from scion_sdk.credentials.provider_profile import (
    ProviderProfileError,
    load_provider_profiles,
    resolve_provider_profile,
    resolve_selected_provider_profile,
)
from scion_sdk.mcp import served_security as ss
from scion_sdk.mcp.served_security import (
    ServedSecurityError,
    ServedSecurityMiddleware,
    ServedSecurityOverride,
    apply_served_security_profile,
)
from scion_sdk.mcp.server import create_mcp_server

ROOT = Path(__file__).resolve().parent.parent


class _Recorder:
    def __init__(self) -> None:
        self.middleware: list[Any] = []

    def add_middleware(self, item: Any) -> None:
        self.middleware.append(item)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.18")
def test_r014_18_stdio_is_untouched_and_network_without_auth_is_refused() -> None:
    assert apply_served_security_profile("stdio", auth_provider=None) is False
    for transport in ("streamable-http", "sse"):
        with pytest.raises(ServedSecurityError, match="no authentication provider"):
            apply_served_security_profile(transport, auth_provider=None, audience="a")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.18")
def test_r014_18_audience_required_and_middleware_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONNECTOR_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("FASTMCP_SERVER_AUTH_JWT_AUDIENCE", raising=False)
    server = _Recorder()
    with pytest.raises(ServedSecurityError, match="audience"):
        apply_served_security_profile(
            "sse", auth_provider=object(), mcp=server, audience=""
        )
    monkeypatch.setenv("CONNECTOR_REQUIRED_SCOPES", "read, write")
    assert apply_served_security_profile(
        "sse", auth_provider=object(), mcp=server, audience="aud"
    )
    (installed,) = server.middleware
    assert isinstance(installed, ServedSecurityMiddleware)
    assert installed._required == {"read", "write"}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.18")
def test_r014_18_override_is_explicit_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(ValueError):
        ServedSecurityOverride("")
    server = _Recorder()
    with caplog.at_level("WARNING"):
        active = apply_served_security_profile(
            "streamable-http",
            auth_provider=None,
            mcp=server,
            override=ServedSecurityOverride("behind the audited mesh gateway"),
        )
    assert active is False and not server.middleware
    assert "OVERRIDDEN" in caplog.text and "audited mesh gateway" in caplog.text


def _token(**kwargs: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "client_id": "svc",
        "scopes": ["read"],
        "claims": {"sub": "u1", "tenant_id": "t1"},
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "session", "scopes", "allowed"),
    [
        (_token(), "s1", frozenset({"read"}), True),
        (None, "s1", frozenset(), False),
        (_token(claims={"sub": "u1"}), "s1", frozenset(), False),
        (_token(client_id="", claims={"tenant_id": "t"}), "s1", frozenset(), False),
        (_token(), "s1", frozenset({"admin"}), False),
        (_token(), "", frozenset(), False),
        (
            _token(claims={"sub": "u", "scope": "read admin", "org": "o"}, scopes=[]),
            "s",
            frozenset({"admin"}),
            True,
        ),
    ],
)
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.18")
async def test_r014_18_middleware_enforces_identity_tenant_acl_session(
    monkeypatch: pytest.MonkeyPatch,
    token: Any,
    session: str,
    scopes: frozenset[str],
    allowed: bool,
) -> None:
    monkeypatch.setattr(ss, "get_access_token", lambda: token)
    context = SimpleNamespace(
        method="tools/call", fastmcp_context=SimpleNamespace(session_id=session)
    )

    async def call_next(_context: Any) -> str:
        return "ok"

    middleware = ServedSecurityMiddleware(scopes)
    if allowed:
        assert await middleware.on_request(context, call_next) == "ok"
    else:
        with pytest.raises(MCPError, match="access denied"):
            await middleware.on_request(context, call_next)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.18")
def test_r014_18_every_server_gets_the_profile_by_default() -> None:
    with pytest.raises(SystemExit):
        create_mcp_server(
            "x", version="1", command_args=["--transport", "streamable-http"]
        )
    _args, mcp, _mw = create_mcp_server("x", version="1", command_args=[])
    assert not any(isinstance(m, ServedSecurityMiddleware) for m in mcp.middleware)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.18")
def test_r014_18_static_token_carries_tenant() -> None:
    from scion_sdk.mcp.auth.policy import AuthConfigurationError
    from scion_sdk.mcp.auth.static import validated_static_tokens

    token = "t" * 40
    ok = validated_static_tokens(
        json.dumps({token: {"client_id": "c", "scopes": [], "tenant_id": "t1"}})
    )
    assert ok[token]["tenant_id"] == "t1"
    with pytest.raises(AuthConfigurationError):
        validated_static_tokens(
            json.dumps({token: {"client_id": "c", "scopes": [], "tenant_id": 7}})
        )


PROFILES = json.dumps(
    {
        "abs-main": {
            "enabled": True,
            "endpoint_ref": "env://ABS_URL",
            "credential_refs": {"TOKEN": "env://ABS_TOKEN"},
            "selector_refs": {"LIBRARY": "env://ABS_LIB"},
            "tls_profile": "system",
        },
        "abs-off": {"enabled": False, "credential_refs": {"TOKEN": "env://ABS_TOKEN"}},
    }
)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.19")
def test_r014_19_selected_profile_resolves_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        PROVIDER_CONFIGS=PROFILES,
        TLS_PROFILES='{"profiles": {"system": {"system_trust": true}}}',
        AGENT_PROVIDER_PROFILE="abs-main",
        ABS_URL="https://abs.example.invalid/",
        ABS_TOKEN="tok-123",
        ABS_LIB="lib-1",
    )
    resolved = resolve_selected_provider_profile()
    assert resolved.endpoint == "https://abs.example.invalid"
    assert resolved.credentials["TOKEN"] == "tok-123"
    assert resolved.selectors["LIBRARY"] == "lib-1"
    assert resolved.tls is not None and resolved.tls.verify_enabled
    assert "tok-123" not in repr(resolved)
    resolved.close()
    resolved.close()
    assert (
        resolved.endpoint is None and not resolved.credentials and resolved.tls is None
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.19")
def test_r014_19_failures_are_stable_codes_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        PROVIDER_CONFIGS=PROFILES,
        ABS_TOKEN="secret-xyz",
        TLS_PROFILES='{"profiles": {"system": {"system_trust": true}}}',
    )
    monkeypatch.delenv("AGENT_PROVIDER_PROFILE", raising=False)
    with pytest.raises(ProviderProfileError, match="provider_profile_not_selected"):
        resolve_selected_provider_profile()
    for name, code in (
        ("Bad Name", "provider_profile_invalid"),
        ("nope-profile", "provider_profile_unavailable"),
        ("abs-off", "provider_profile_disabled"),
    ):
        with pytest.raises(ProviderProfileError, match=code):
            resolve_provider_profile(name)
    monkeypatch.delenv("ABS_URL", raising=False)
    with pytest.raises(ProviderProfileError) as info:
        resolve_provider_profile("abs-main")
    assert str(info.value) == "provider_runtime_reference_unavailable"
    _env(monkeypatch, ABS_URL="http://public.example.invalid", ABS_LIB="x")
    with pytest.raises(ProviderProfileError, match="provider_endpoint_invalid"):
        resolve_provider_profile("abs-main")
    _env(monkeypatch, ABS_URL="https://abs.example.invalid", ABS_LIB="a\nb")
    with pytest.raises(ProviderProfileError, match="provider_selector_invalid"):
        resolve_provider_profile("abs-main")


@pytest.mark.parametrize(
    "document",
    [
        "{not json",
        '{"a-b": {}, "a-b": {}}',
        '{"UPPER": {"enabled": false}}',
        '{"abc": {"enabled": true}}',
        '{"abc": {"credential_refs": {"TOKEN": "plain-secret"}}}',
        '{"abc": {"unknown": 1}}',
        '{"abc": {"endpoint_ref": "env://X"}}',
        '{"abc": {"endpoint_ref": "env://X", "tls_profile": "t", "tls_profile_ref": "env://Y"}}',
        '{"abc": {"credential_refs": {"A": "env://X"}, "selector_refs": {"A": "env://Y"}}}',
        "[]",
    ],
)
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.19")
def test_r014_19_invalid_profile_documents_are_refused(document: str) -> None:
    with pytest.raises(ProviderProfileError, match="provider_profiles_invalid"):
        load_provider_profiles(document)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.19")
def test_r014_19_empty_configuration_has_no_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROVIDER_CONFIGS", raising=False)
    assert load_provider_profiles() == {}
    assert pp.ProviderProfile().enabled is False


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.20")
def test_r014_20_entry_point_groups_use_the_sdk_namespace() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    groups = set(project["project"]["entry-points"])
    assert groups == {
        "scion_sdk.source_adapters",
        "scion_sdk.artifact_kinds",
        "scion_sdk.transports",
        "scion_sdk.sinks",
        "scion_sdk.skill_providers",
        "pytest11",
    }
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "scion_sdk").rglob("*")
        if path.suffix in {".py", ".md"}
        and re.search(
            r"agent_utilities\.\w+_providers", path.read_text(errors="ignore")
        )
    ]
    assert offenders == []
