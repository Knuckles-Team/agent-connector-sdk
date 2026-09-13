"""TLS profile selection, material resolution and client adapters."""

from __future__ import annotations

import ssl
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from agent_connector_sdk.credentials.references import SecretReference
from agent_connector_sdk.credentials.resolver import (
    CompositeCredentialResolver,
    CredentialUnavailableError,
    EnvironmentCredentialResolver,
)
from agent_connector_sdk.testing.certificates import (
    CertificateSet,
    issue_test_certificates,
)
from agent_connector_sdk.tls.context import (
    build_ssl_context,
    minimum_tls_version,
    unencrypted_key_pem,
)
from agent_connector_sdk.tls.errors import TransportSecurityError
from agent_connector_sdk.tls.material import (
    MAX_PEM_BYTES,
    MaterialStore,
    default_runtime_root,
    existing_path,
)
from agent_connector_sdk.tls.profile import ResolvedTLSProfile
from agent_connector_sdk.tls.resolve import resolve_tls_profile
from agent_connector_sdk.tls.selection import (
    SelectedProfile,
    select_profile,
    service_prefix,
)


class _Vault:
    """An in-memory ``openbao://`` resolver."""

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def resolve(self, reference: SecretReference) -> str:
        value = self.values.get(reference.render())
        if value is None:
            raise CredentialUnavailableError("secret reference is unavailable")
        return value


def _resolver(values: dict[str, str]) -> CompositeCredentialResolver:
    return CompositeCredentialResolver(
        {"env": EnvironmentCredentialResolver(), "openbao": _Vault(values)}
    )


@pytest.fixture(scope="module")
def certificates() -> CertificateSet:
    return issue_test_certificates()


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "TLS_PROFILES",
        "TLS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))


def test_service_prefix_and_default_environment_profile() -> None:
    assert service_prefix(" gitlab-api ") == "GITLAB_API"
    with pytest.raises(TransportSecurityError, match="tls_service_invalid"):
        service_prefix("--")
    profile = resolve_tls_profile("demo")
    assert (profile.source, profile.configured, profile.system_trust) == (
        "environment",
        False,
        True,
    )
    assert profile.verify_enabled and profile.ssl_context.check_hostname
    assert profile.minimum_version == ssl.TLSVersion.TLSv1_2
    assert "ssl_context" not in repr(profile)


def test_environment_ca_minimum_version_and_proxy(
    monkeypatch: pytest.MonkeyPatch, certificates: CertificateSet, tmp_path: Path
) -> None:
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text(certificates.ca_pem)
    monkeypatch.setenv("DEMO_CA_BUNDLE", str(ca_file))
    monkeypatch.setenv("DEMO_TLS_MINIMUM_VERSION", "TLSv1.3")
    monkeypatch.setenv("TLS_PROXY_URL", "http://proxy.example.invalid:3128")
    profile = resolve_tls_profile("demo")
    assert profile.configured and profile.ca_bundle_path == ca_file
    assert profile.ssl_context.minimum_version == ssl.TLSVersion.TLSv1_3
    assert profile.httpx_kwargs()["proxy"] == "http://proxy.example.invalid:3128"
    assert profile.requests_kwargs() == {
        "verify": str(ca_file),
        "proxies": {
            "http": "http://proxy.example.invalid:3128",
            "https": "http://proxy.example.invalid:3128",
        },
    }


def test_standard_ca_fallback(
    monkeypatch: pytest.MonkeyPatch, certificates: CertificateSet, tmp_path: Path
) -> None:
    ca_file = tmp_path / "bundle.pem"
    ca_file.write_text(certificates.ca_pem)
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
    assert resolve_tls_profile("demo").ca_bundle_path == ca_file


def test_catalog_and_secret_reference_profiles(
    monkeypatch: pytest.MonkeyPatch, certificates: CertificateSet
) -> None:
    catalog = '{"profiles": {"internal": {"ca_bundle_ref": "openbao://apps/demo#CA", "system_trust": false}}}'
    resolver = _resolver(
        {
            "openbao://apps/demo#CA": certificates.ca_pem,
            "openbao://apps/demo#TLS": catalog,
        }
    )
    monkeypatch.setenv("TLS_PROFILES", catalog)
    monkeypatch.setenv("DEMO_TLS_PROFILE", "internal")
    from_catalog = resolve_tls_profile("demo", resolver=resolver)
    assert (from_catalog.name, from_catalog.source, from_catalog.system_trust) == (
        "internal",
        "runtime_catalog",
        False,
    )
    material = from_catalog.ca_bundle_path
    assert material is not None and material.stat().st_mode & 0o777 == 0o600
    from_catalog.cleanup()
    assert not material.exists()
    from_ref = resolve_tls_profile(
        "demo",
        profile_name="internal",
        profile_ref="openbao://apps/demo#TLS",
        resolver=resolver,
    )
    assert from_ref.source == "secret_ref"
    monkeypatch.setenv("TLS_PROFILES_REF", "openbao://apps/demo#TLS")
    assert resolve_tls_profile("demo", resolver=resolver).source == "secret_catalog"


def test_selection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(reference: str) -> str:
        return {"env://BIG": "x" * 300_000, "env://LIST": "[]"}.get(reference, "{}")

    selected = select_profile(
        "demo",
        profile_name=None,
        profile_ref=None,
        profile={"no_proxy": "a"},
        resolve=resolve,
    )
    assert selected == SelectedProfile("inline", "inline", True, {"no_proxy": "a"})
    cases: list[tuple[str | None, str | None, dict[str, str] | None, str]] = [
        ("missing", None, None, "tls_profile_catalog_unavailable"),
        (None, "env://BIG", None, "tls_profile_too_large"),
        (None, "env://LIST", None, "tls_profile_invalid"),
        ("bad name", "env://OBJ", None, "tls_profile_name_invalid"),
        ("absent", "env://OBJ", None, "tls_profile_not_found"),
        (
            None,
            None,
            {"client_key_password": "hunter2"},
            "tls_credential_value_in_configuration",
        ),
    ]
    for name, ref, document, code in cases:
        with pytest.raises(TransportSecurityError, match=code):
            select_profile(
                "demo",
                profile_name=name,
                profile_ref=ref,
                profile=document,
                resolve=resolve,
            )
    monkeypatch.setenv("TLS_PROFILES", "not json")
    with pytest.raises(TransportSecurityError, match="tls_profile_invalid"):
        select_profile(
            "demo", profile_name="x", profile_ref=None, profile=None, resolve=resolve
        )


def test_resolution_rejects_unsafe_profiles(
    certificates: CertificateSet, tmp_path: Path
) -> None:
    cases = [
        ({"verify": False}, "tls_verification_control_rejected"),
        ({"allow_insecure": True}, "tls_verification_control_rejected"),
        ({"system_trust": False}, "tls_trust_anchor_missing"),
        ({"system_trust": "maybe"}, "tls_profile_boolean_invalid"),
        ({"minimum_version": "TLSv1.1"}, "tls_minimum_version_invalid"),
        (
            {"ca_bundle_pem": certificates.ca_pem, "ca_bundle_path": "/x"},
            "tls_material_source_ambiguous",
        ),
        ({"ca_bundle_pem": "not a certificate"}, "tls_material_invalid"),
        ({"ca_bundle_path": str(tmp_path / "missing.pem")}, "tls_material_unavailable"),
        (
            {"client_cert_pem": certificates.server_cert_pem},
            "tls_client_certificate_incomplete",
        ),
        ({"proxy_url": "ftp://proxy.example.invalid"}, "tls_proxy_invalid"),
        (
            {
                "proxy_url": "http://"
                + ":".join(("user", "pw"))
                + "@proxy.example.invalid"
            },
            "tls_proxy_invalid",
        ),
        (
            {"proxy_url": "http://p.invalid", "proxy_url_ref": "env://P"},
            "proxy_url_source_ambiguous",
        ),
        ({"ca_bundle_ref": "env://DEMO_TLS_NOT_SET"}, "tls_secret_unavailable"),
    ]
    for document, code in cases:
        with pytest.raises(TransportSecurityError, match=code):
            resolve_tls_profile("demo", profile=document, runtime_root=tmp_path / "rt")
    assert not list((tmp_path / "rt").glob("*")) if (tmp_path / "rt").exists() else True


def test_client_certificate_with_encrypted_key(
    certificates: CertificateSet, tmp_path: Path
) -> None:
    key = serialization.load_pem_private_key(
        certificates.server_key_pem.encode(), password=None
    )
    encrypted = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"pass-phrase"),
    ).decode()
    secrets = {
        "openbao://apps/demo#KEY": encrypted,
        "openbao://apps/demo#PASS": "pass-phrase",
        "openbao://apps/demo#CERT": certificates.server_cert_pem,
    }
    profile = resolve_tls_profile(
        "demo",
        profile={
            "client_cert_ref": "openbao://apps/demo#CERT",
            "client_key_ref": "openbao://apps/demo#KEY",
            "client_key_password_ref": "openbao://apps/demo#PASS",
        },
        resolver=_resolver(secrets),
        runtime_root=tmp_path / "rt",
    )
    bundle = profile.client_bundle_path
    assert bundle is not None and "ENCRYPTED" not in bundle.read_text()
    assert profile.requests_kwargs()["cert"] == str(bundle)
    assert profile.pymongo_kwargs() == {
        "tls": True,
        "tlsCertificateKeyFile": str(bundle),
    }
    postgres = profile.psycopg_kwargs()
    assert (
        postgres["sslmode"] == "verify-full"
        and postgres["sslpassword"] == "pass-phrase"
    )
    assert postgres["ssl_min_protocol_version"] == "TLSv1.2"
    assert len(profile.materialized) == 3
    profile.cleanup()
    assert not any(path.exists() for path in profile.materialized)


def test_database_adapters_reject_proxies(tmp_path: Path) -> None:
    profile = resolve_tls_profile(
        "demo", profile={"proxy_url": "http://proxy.example.invalid"}
    )
    with pytest.raises(TransportSecurityError, match="postgres"):
        profile.psycopg_kwargs()
    with pytest.raises(TransportSecurityError, match="mongodb"):
        profile.pymongo_kwargs()


def test_configure_requests_session(certificates: CertificateSet) -> None:
    class Session:
        def __init__(self) -> None:
            self.trust_env, self.verify, self.cert, self.proxies = True, True, None, {}

    profile = resolve_tls_profile(
        "demo",
        profile={
            "ca_bundle_pem": certificates.ca_pem,
            "trust_env": "false",
            "proxy_url": "http://p.invalid",
        },
    )
    session = profile.configure_requests_session(Session())
    assert session.trust_env is False and session.verify == str(profile.ca_bundle_path)
    assert session.proxies["https"] == "http://p.invalid"
    profile.cleanup()


def test_context_and_material_helpers(
    certificates: CertificateSet, tmp_path: Path
) -> None:
    assert minimum_tls_version(None) == ssl.TLSVersion.TLSv1_2
    context = build_ssl_context(
        system_trust=False,
        ca_file=None,
        ca_directory=tmp_path,
        minimum_version=ssl.TLSVersion.TLSv1_3,
    )
    assert context.verify_mode == ssl.CERT_REQUIRED
    key_file = tmp_path / "key.pem"
    key_file.write_text(certificates.server_key_pem)
    assert unencrypted_key_pem(key_file, None) == certificates.server_key_pem
    store = MaterialStore(tmp_path / "store")
    written = store.write(
        certificates.server_cert_pem + certificates.server_key_pem, kind="bundle"
    )
    assert written.parent.stat().st_mode & 0o777 == 0o700
    store.discard()
    assert not written.exists() and store.created == []
    assert existing_path(str(tmp_path), directory=True) == tmp_path
    with pytest.raises(TransportSecurityError, match="tls_material_path_invalid"):
        existing_path("")
    big = tmp_path / "big.pem"
    big.write_bytes(b"x" * (MAX_PEM_BYTES + 1))
    with pytest.raises(TransportSecurityError, match="tls_material_too_large"):
        existing_path(big)
    assert default_runtime_root().parts[-2:] == ("agent-connector-sdk", "tls")


def test_wrapped_material_failure_names_the_cause_and_cleans_up(
    certificates: CertificateSet, tmp_path: Path
) -> None:
    other_key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_file = tmp_path / "mismatched.key"
    key_file.write_bytes(other_key)
    runtime = tmp_path / "rt"
    with pytest.raises(
        TransportSecurityError, match=r"tls_profile_material_invalid \(SSLError\)"
    ):
        resolve_tls_profile(
            "demo",
            profile={
                "client_cert_pem": certificates.server_cert_pem,
                "client_key_path": str(key_file),
            },
            runtime_root=runtime,
        )
    assert list(runtime.iterdir()) == []


def test_resolved_profile_is_a_plain_value(certificates: CertificateSet) -> None:
    profile = ResolvedTLSProfile(
        name="n",
        source="inline",
        configured=True,
        system_trust=True,
        trust_env=False,
        ssl_context=ssl.create_default_context(),
    )
    assert profile.httpx_kwargs()[
        "trust_env"
    ] is False and profile.requests_kwargs() == {"verify": True}
