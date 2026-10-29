"""Release signatures bind both inputs and an explicitly trusted key."""

import base64
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rdflib import Graph, Literal, URIRef

from agent_connector_sdk.credentials.provider import (
    CredentialProvider,
    CredentialScopeError,
)
from agent_connector_sdk.credentials.references import parse_secret_reference
from agent_connector_sdk.ingest.sources import IngestSourceDeclaration
from agent_connector_sdk.manifest.release_signature import (
    ReleaseSignature,
    ReleaseSigningError,
    sign_release,
    verify_release,
)


class FixtureResolver:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def resolve(self, reference: object) -> str:
        self.calls += 1
        return self.value


def fixture():
    seed = bytes(range(32))
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    resolver = FixtureResolver(base64.urlsafe_b64encode(seed).decode().rstrip("="))
    provider = CredentialProvider(resolver, "example")
    declaration = IngestSourceDeclaration(connector="example")
    graph = Graph()
    graph.add((URIRef("urn:a"), URIRef("urn:b"), Literal("value")))
    reference = parse_secret_reference("openbao://apps/example/signing#seed@1")
    return declaration, graph, reference, resolver, provider, {"key-1": public}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.3")
def test_release_signing_binds_declaration_graph_and_trusted_key() -> None:
    declaration, graph, reference, resolver, provider, trusted = fixture()
    evidence = sign_release(
        declaration,
        graph,
        key_id="key-1",
        key_reference=reference,
        provider=provider,
        trusted_keys=trusted,
    )
    assert isinstance(evidence, ReleaseSignature)
    assert resolver.calls == 1
    assert verify_release(declaration, graph, evidence, trusted_keys=trusted)
    assert not verify_release(
        declaration.model_copy(update={"connector": "other"}),
        graph,
        evidence,
        trusted_keys=trusted,
    )
    changed = Graph()
    assert not verify_release(declaration, changed, evidence, trusted_keys=trusted)
    assert not verify_release(
        declaration, graph, replace(evidence, key_id="unknown"), trusted_keys=trusted
    )
    assert not verify_release(
        declaration,
        graph,
        replace(evidence, signature=evidence.signature + "="),
        trusted_keys=trusted,
    )
    assert not verify_release(declaration, graph, evidence, trusted_keys={})
    aliased = {**trusted, "key-2": trusted["key-1"]}
    assert not verify_release(
        declaration, graph, replace(evidence, key_id="key-2"), trusted_keys=aliased
    )
    assert not verify_release(
        declaration, graph, replace(evidence, digest="0" * 64), trusted_keys=trusted
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.3")
def test_signing_refuses_unversioned_and_untrusted_keys() -> None:
    declaration, graph, _, resolver, provider, trusted = fixture()
    for reference in ("env://RELEASE_SEED", "openbao://apps/example/signing#seed"):
        with pytest.raises(ReleaseSigningError):
            sign_release(
                declaration,
                graph,
                key_id="key-1",
                key_reference=parse_secret_reference(reference),
                provider=provider,
                trusted_keys=trusted,
            )
    assert resolver.calls == 0
    with pytest.raises(ReleaseSigningError):
        sign_release(
            declaration,
            graph,
            key_id="key-1",
            key_reference=parse_secret_reference(
                "openbao://apps/example/signing#seed@1"
            ),
            provider=provider,
            trusted_keys={"key-1": bytes(32)},
        )

    with pytest.raises(CredentialScopeError):
        sign_release(
            declaration,
            graph,
            key_id="key-1",
            key_reference=parse_secret_reference(
                "openbao://apps/another/signing#seed@1"
            ),
            provider=provider,
            trusted_keys=trusted,
        )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.2")
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.3")
def test_invalid_mutated_declaration_is_never_signed_or_verified() -> None:
    declaration, graph, reference, resolver, provider, trusted = fixture()
    evidence = sign_release(
        declaration,
        graph,
        key_id="key-1",
        key_reference=reference,
        provider=provider,
        trusted_keys=trusted,
    )
    declaration.schema_mappings["bad"] = {"ontology_class": 123}  # type: ignore[assignment]
    invalid = declaration
    assert not verify_release(invalid, graph, evidence, trusted_keys=trusted)
    with pytest.raises(ValueError):
        sign_release(
            invalid,
            graph,
            key_id="key-1",
            key_reference=reference,
            provider=provider,
            trusted_keys=trusted,
        )
    assert resolver.calls == 1
