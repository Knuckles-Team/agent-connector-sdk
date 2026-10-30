"""SCION-CONNECTOR-CONTROL-R014.2-R014.9: connector runtime utilities moved from agent-utilities."""

from __future__ import annotations

import argparse
import asyncio
import os

import pytest

from scion_sdk import file_lock, paths
from scion_sdk.auth.delegation import (
    DelegationSettings,
    get_delegated_token,
    is_delegation_enabled,
)
from scion_sdk.credentials.provider import NoCredential
from scion_sdk.credentials.runtime_references import (
    RuntimeSecretReferenceAction,
    RuntimeSecretReferenceError,
    resolve_runtime_secret_reference,
    validate_runtime_secret_reference,
)
from scion_sdk.exceptions import LoginRequiredError
from scion_sdk.http.egress import (
    egress_ip_is_blocked,
    validate_base_url,
    validate_base_url_resolved,
)
from scion_sdk.mcp.versioning import tool_version
from scion_sdk.privacy_pii import PiiSanitizer


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.2")
def test_r014_2_file_lock_exclusive_and_nonblocking(tmp_path):
    target = tmp_path / "lease.lock"
    first = os.open(target, os.O_RDWR | os.O_CREAT)
    second = os.open(target, os.O_RDWR | os.O_CREAT)
    try:
        assert file_lock.lock_exclusive(first) is True
        with pytest.raises(file_lock.LockUnavailable):
            file_lock.lock_exclusive_nb(second)
        assert file_lock.lock_exclusive(second, blocking=False) is False
        file_lock.unlock(first)
        file_lock.lock_exclusive_nb(second)
        file_lock.unlock(second)
        file_lock.unlock(second)  # idempotent
    finally:
        os.close(first)
        os.close(second)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.3")
def test_r014_3_tool_version_stamps_async_tool():
    @tool_version("1.2.0")
    async def search(query: str) -> str:
        """Search things."""
        return query

    assert search.__agentic_version__ == "1.2.0"
    assert "Version: 1.2.0" in (search.__doc__ or "")
    assert asyncio.run(search("x")) == "x"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.4")
def test_r014_4_runtime_secret_references(monkeypatch):
    monkeypatch.setenv("ACS_TEST_TOKEN", "s3cret")
    assert resolve_runtime_secret_reference("env://ACS_TEST_TOKEN") == "s3cret"
    assert validate_runtime_secret_reference(" env://X ") == "env://X"
    for bad in ("", "plain-value", "ftp://x", "env://bad name", "vault://a/../b#f"):
        with pytest.raises(RuntimeSecretReferenceError) as info:
            validate_runtime_secret_reference(bad)
        assert "s3cret" not in str(info.value)
    monkeypatch.delenv("ACS_TEST_MISSING", raising=False)
    with pytest.raises(RuntimeSecretReferenceError) as info:
        resolve_runtime_secret_reference("env://ACS_TEST_MISSING")
    assert "ACS_TEST_MISSING" not in str(info.value)
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", action=RuntimeSecretReferenceAction)
    assert parser.parse_args(["--token", "env://ACS_TEST_TOKEN"]).token == "s3cret"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.5")
def test_r014_5_validate_base_url():
    assert validate_base_url("https://example.com").allowed
    assert not validate_base_url("ftp://example.com").allowed
    assert not validate_base_url(
        "https://u:p@example.com"  # sanitizer:ignore - synthetic fixture
    ).allowed
    assert not validate_base_url("http://10.0.0.1").allowed
    assert not validate_base_url("http://169.254.169.254").allowed
    assert validate_base_url("http://127.0.0.1").allowed
    assert not validate_base_url("http://127.0.0.1", allow_loopback=False).allowed
    assert egress_ip_is_blocked("not-an-ip", allow_loopback=True)

    def resolver(host, *_args, **_kwargs):
        return [(2, 1, 6, "", ("10.1.2.3", 0))]

    assert not validate_base_url_resolved(
        "https://evil.example", resolver=resolver
    ).allowed


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.6")
def test_r014_6_pii_sanitizer_redacts():
    sanitizer = PiiSanitizer()
    out = sanitizer.sanitize("mail alice@example.com now")
    assert "alice@example.com" not in str(out)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.7")
def test_r014_7_paths_honour_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("CONNECTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("CONNECTOR_DATA_DIR", raising=False)
    monkeypatch.delenv("CONNECTOR_RESEARCH_DIR", raising=False)
    assert paths.log_dir() == tmp_path / "logs"
    assert paths.data_dir() == tmp_path / "data" / "agent-connectors"
    assert paths.research_dir().is_dir()


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.8")
def test_r014_8_delegation_helpers():
    assert is_delegation_enabled(DelegationSettings()) is False
    import httpx

    with httpx.Client() as client, pytest.raises(LoginRequiredError):
        get_delegated_token(http_client=client, settings=DelegationSettings())


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.9")
def test_r014_9_no_credential():
    cred = NoCredential()
    assert cred.is_present() and cred.headers() == {} and cred.type_name == "none"
