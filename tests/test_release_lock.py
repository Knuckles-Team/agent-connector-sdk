"""Explicit ontology locks supply key pins without accepting ambiguity."""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rdflib import Graph

from agent_connector_sdk.credentials.provider import CredentialProvider
from agent_connector_sdk.credentials.references import parse_secret_reference
from agent_connector_sdk.ingest.sources import IngestSourceDeclaration
from agent_connector_sdk.manifest import (
    MAX_RELEASE_LOCK_BYTES,
    create_release_key_lock,
    load_release_key_lock,
)
from agent_connector_sdk.manifest.release_signature import (
    ReleaseSigningError,
    sign_release,
    verify_release,
)


class Resolver:
    def resolve(self, reference):
        return base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


def encoded_public() -> str:
    public = (
        Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return base64.urlsafe_b64encode(public).decode().rstrip("=")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.4")
def test_explicit_lock_pins_signing_and_verification(tmp_path) -> None:
    lock = tmp_path / "ontology.lock"
    lock.write_text(
        f"a: {{signer: demo, signing_public_key: {encoded_public()}}}\n",
        encoding="utf-8",
    )
    trusted = load_release_key_lock(lock)
    declaration = IngestSourceDeclaration(connector="example")
    graph = Graph()
    reference = parse_secret_reference("openbao://apps/example/signing#seed@1")
    evidence = sign_release(
        declaration,
        graph,
        key_id="demo",
        key_reference=reference,
        provider=CredentialProvider(Resolver(), "example"),
        trusted_keys=trusted,
    )
    assert verify_release(declaration, graph, evidence, trusted_keys=trusted)
    with pytest.raises(TypeError):
        trusted["new"] = bytes(32)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.4")
def test_ambiguous_or_untrusted_locks_refuse(tmp_path) -> None:
    lock = tmp_path / "ontology.lock"
    first = encoded_public()
    second = base64.urlsafe_b64encode(bytes(32)).decode().rstrip("=")
    for text in (
        "",
        "a: {signer: demo}\n",
        f"a: {{signer: demo, signer: other, signing_public_key: {first}}}\n",
        f"a: {{signer: demo, signing_public_key: {first}=}}\n",
        f"a: {{signer: demo, signing_public_key: {first}}}\nb: {{signer: demo, signing_public_key: {second}}}\n",
        "x" * (MAX_RELEASE_LOCK_BYTES + 1),
    ):
        lock.write_text(text, encoding="utf-8")
        with pytest.raises(ReleaseSigningError):
            load_release_key_lock(lock)
    lock.unlink()
    with pytest.raises(ReleaseSigningError):
        load_release_key_lock(lock)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.5")
def test_create_release_lock_round_trips_without_overwriting(tmp_path) -> None:
    lock = tmp_path / "ontology.lock"
    key = base64.urlsafe_b64decode(encoded_public() + "=")
    create_release_key_lock(lock, {"artifact": ("demo", key)})
    assert load_release_key_lock(lock) == {"demo": key}
    before = lock.read_bytes()
    with pytest.raises(ReleaseSigningError):
        create_release_key_lock(lock, {"artifact": ("demo", bytes(32))})
    assert lock.read_bytes() == before
    assert list(tmp_path.iterdir()) == [lock]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.5")
def test_create_release_lock_refuses_invalid_inputs_without_a_file(tmp_path) -> None:
    lock = tmp_path / "ontology.lock"
    for artifacts in (
        {},
        {"a": ("bad signer", bytes(32))},
        {"a": ("demo", b"short")},
        {"a": ("demo", bytes(32)), "b": ("demo", bytes([1]) * 32)},
    ):
        with pytest.raises(ReleaseSigningError):
            create_release_key_lock(lock, artifacts)
        assert not lock.exists()


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.5")
def test_create_release_lock_refuses_symlink_without_touching_target(tmp_path) -> None:
    target = tmp_path / "existing"
    target.write_text("keep")
    lock = tmp_path / "ontology.lock"
    lock.symlink_to(target)
    with pytest.raises(ReleaseSigningError):
        create_release_key_lock(lock, {"artifact": ("demo", bytes(32))})
    assert target.read_text() == "keep"
    assert lock.is_symlink()
