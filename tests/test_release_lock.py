"""Explicit ontology locks supply key pins without accepting ambiguity."""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rdflib import Graph

from agent_connector_sdk.credentials.provider import CredentialProvider
from agent_connector_sdk.credentials.references import parse_secret_reference
from agent_connector_sdk.ingest.sources import IngestSourceDeclaration
from agent_connector_sdk.manifest import MAX_RELEASE_LOCK_BYTES, load_release_key_lock
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


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R650.4")
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


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R650.4")
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
