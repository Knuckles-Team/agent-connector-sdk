"""Bound wallet signatures are proof facts, never authorization grants."""

import base64
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_connector_sdk.writeback import (
    WalletKeyResolver,
    WalletKeyTrust,
    WalletProofBinding,
    WalletProofRequest,
    WalletProofResult,
    WalletSignatureVerifier,
)


def _fixture():
    binding = WalletProofBinding(
        tenant_id="tenant",
        actor_id="actor",
        connector_id="connector",
        operation_id="pay",
        account_id="account",
        wallet_id="wallet",
        network_id="network",
        key_id="key",
        plan_digest="a" * 64,
        change_set_digest="b" * 64,
        change_set_id="change",
        idempotency_key="effect",
    )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    trust = WalletKeyTrust(binding, public, "signer", "revision", 900, 1400, False)
    request = WalletProofRequest(
        tenant_id=binding.tenant_id,
        actor_id=binding.actor_id,
        connector_id=binding.connector_id,
        operation_id=binding.operation_id,
        account_id=binding.account_id,
        wallet_id=binding.wallet_id,
        network_id=binding.network_id,
        key_id=binding.key_id,
        plan_digest=binding.plan_digest,
        change_set_digest=binding.change_set_digest,
        idempotency_key=binding.idempotency_key,
        scheme="ed25519_jcs",
        nonce=binding.change_set_id,
        issued_at=1000,
        expires_at=1100,
        signature=base64.urlsafe_b64encode(bytes(64)).decode().rstrip("="),
    )
    signature = (
        base64.urlsafe_b64encode(key.sign(request.signed_bytes())).decode().rstrip("=")
    )
    return binding, trust, request.model_copy(update={"signature": signature})


class _Resolver(WalletKeyResolver):
    def __init__(self, result):
        self.result = result

    async def resolve(self, binding):
        return self.result


async def test_signed_exact_binding_and_refusals():
    binding, trust, request = _fixture()
    result = await WalletSignatureVerifier(_Resolver(trust)).verify(
        request, binding, now=1050
    )
    assert isinstance(result, WalletProofResult)
    assert result.outcome == "verified"
    assert result.signer_ref == "signer" and result.trust_revision == "revision"
    assert result.payload_digest and "signature" not in result.model_dump_json()
    cases = [
        (request, replace(binding, tenant_id="other"), trust, 1050, "scope_mismatch"),
        (request, binding, trust, 1100, "expired"),
        (request, binding, replace(trust, revoked=True), 1050, "revoked_key"),
        (request, binding, None, 1050, "untrusted_key"),
        (
            request.model_copy(update={"scheme": "other"}),
            binding,
            trust,
            1050,
            "unsupported_scheme",
        ),
        (
            request.model_copy(
                update={
                    "signature": base64.urlsafe_b64encode(bytes(64))
                    .decode()
                    .rstrip("=")
                }
            ),
            binding,
            trust,
            1050,
            "invalid_signature",
        ),
        (
            request.model_copy(update={"issued_at": True}),
            binding,
            trust,
            1050,
            "invalid_payload",
        ),
    ]
    for proof, expected, trusted, now, reason in cases:
        result = await WalletSignatureVerifier(_Resolver(trusted)).verify(
            proof, expected, now=now
        )
        assert result.outcome == "refused" and result.reason == reason


async def test_unavailable_trust_fails_closed():
    binding, _, request = _fixture()

    class _Unavailable:
        async def resolve(self, binding):
            raise RuntimeError("sensitive upstream details")

    result = await WalletSignatureVerifier(_Unavailable()).verify(
        request, binding, now=1050
    )
    assert result.reason == "verification_unavailable"
    assert "sensitive" not in result.model_dump_json()


def test_jcs_bytes_are_stable_and_bind_unicode():
    _, _, request = _fixture()
    payload = request.model_copy(update={"wallet_id": "雪"}).signed_bytes()
    assert payload.startswith(b"SDK-WALLET-INTENT\x001\x00{")
    assert b'"wallet_id":"\xe9\x9b\xaa"' in payload
    assert b'"signature"' not in payload


def test_ed25519_rfc8032_empty_message_vector():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    public_key = bytes.fromhex(
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    )
    signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, b"")


def test_wire_refuses_duplicate_fields():
    _, _, request = _fixture()
    wire = request.model_dump_json().encode()
    assert WalletProofRequest.from_wire_json(wire) == request
    duplicate = wire.replace(
        b'"tenant_id":"tenant"', b'"tenant_id":"tenant","tenant_id":"other"'
    )
    with pytest.raises(ValueError, match="duplicate"):
        WalletProofRequest.from_wire_json(duplicate)
