"""Wallet proof is verified before a governed effect and never replaces approval."""

import base64
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.testing.writeback_audit import InMemoryAuditReservation
from agent_connector_sdk.writeback import (
    WalletKeyTrust,
    WalletProofBinding,
    WalletProofRequest,
    WalletProofResult,
    WalletSignatureVerifier,
)
from agent_connector_sdk.writeback.authorization import (
    DeterministicAuthorizationVerifier,
)
from agent_connector_sdk.writeback.errors import (
    AuthorizationDeniedError,
    WalletProofRefusedError,
)
from agent_connector_sdk.writeback.service import GovernedWriteBack

NOW = 1050


class _Gate:
    """Pairs a received proof with the authenticated binding of the change set."""

    def __init__(self, proof, trust_for, now=NOW):
        self.proof, self.trust_for, self.now = proof, trust_for, now
        self.calls = 0

    async def verify(self, change_set):
        self.calls += 1
        binding = _binding(change_set)

        class _Resolver:
            async def resolve(_, wanted):
                return self.trust_for(wanted)

        return await WalletSignatureVerifier(_Resolver()).verify(
            self.proof, binding, now=self.now
        )


def _binding(change_set):
    return WalletProofBinding(
        tenant_id=change_set.tenant_id,
        actor_id="actor",
        connector_id=change_set.connector_id,
        operation_id="pay",
        account_id="account",
        wallet_id="wallet",
        network_id="network",
        key_id="key",
        plan_digest="a" * 64,
        change_set_digest=change_set.change_set_digest,
        change_set_id=change_set.change_set_id,
        idempotency_key=change_set.idempotency_key,
    )


def _signed(change_set):
    binding = _binding(change_set)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    unsigned = WalletProofRequest(
        **{
            name: getattr(binding, name)
            for name in (
                "tenant_id",
                "actor_id",
                "connector_id",
                "operation_id",
                "account_id",
                "wallet_id",
                "network_id",
                "key_id",
                "plan_digest",
                "change_set_digest",
                "idempotency_key",
            )
        },
        scheme="ed25519_jcs",
        nonce=binding.change_set_id,
        issued_at=1000,
        expires_at=1100,
        signature="A" * 86,
    )
    signature = base64.urlsafe_b64encode(key.sign(unsigned.signed_bytes()))
    proof = unsigned.model_copy(update={"signature": signature.decode().rstrip("=")})
    trust = WalletKeyTrust(binding, public, "signer", "revision", 900, 1400, False)
    return proof, trust


def _port(fixture, gate, *, authorized=True):
    verifier = DeterministicAuthorizationVerifier()
    if authorized:
        verifier.grant(fixture.change_set)
    return GovernedWriteBack(
        fixture.transport, verifier, InMemoryAuditReservation(), proof_gate=gate
    )


async def _status(fixture):
    return (await fixture.transport.read_current(fixture.change_set)).fields["status"]


def test_proof_models_are_closed_and_a_result_is_not_an_authorization_grant():
    fixture = make_writeback_fixture()
    proof, _ = _signed(fixture.change_set)
    with pytest.raises(ValidationError):
        WalletProofRequest.model_validate({**proof.model_dump(), "authorized": True})
    with pytest.raises(ValidationError):
        WalletProofResult.model_validate(
            {"outcome": "verified", "reason": "verified", "authorized": True}
        )
    assert "authorized" not in WalletProofResult.model_fields
    with pytest.raises(ValidationError):
        proof.tenant_id = "other"  # type: ignore[misc]


async def test_verified_proof_precedes_one_effect_but_does_not_replace_approval():
    fixture = make_writeback_fixture()
    proof, trust = _signed(fixture.change_set)
    gate = _Gate(proof, lambda _: trust)
    attempt = await _port(fixture, gate).apply(fixture.change_set)
    assert attempt.idempotency_key == fixture.change_set.idempotency_key
    assert await _status(fixture) == "approved"
    assert gate.calls >= 1

    unapproved = make_writeback_fixture()
    proof, trust = _signed(unapproved.change_set)
    with pytest.raises(AuthorizationDeniedError):
        await _port(unapproved, _Gate(proof, lambda _: trust), authorized=False).apply(
            unapproved.change_set
        )
    assert await _status(unapproved) == "new"


def _expired(proof, trust):
    return _Gate(proof, lambda _: trust, now=1100)


def _revoked(proof, trust):
    return _Gate(proof, lambda _: replace(trust, revoked=True))


def _untrusted(proof, trust):
    return _Gate(proof, lambda _: None)


def _wrong_key_binding(proof, trust):
    return _Gate(
        proof, lambda _: replace(trust, binding=replace(trust.binding, key_id="x"))
    )


def _unsupported(proof, trust):
    return _Gate(proof.model_copy(update={"scheme": "other"}), lambda _: trust)


def _bad_signature(proof, trust):
    return _Gate(proof.model_copy(update={"signature": "A" * 86}), lambda _: trust)


def _wrong_scope(proof, trust):
    return _Gate(proof.model_copy(update={"tenant_id": "other"}), lambda _: trust)


def _unavailable(proof, trust):
    def boom(_):
        raise RuntimeError("sensitive upstream detail")

    return _Gate(proof, boom)


@pytest.mark.parametrize(
    "make_gate,reason",
    [
        (_expired, "expired"),
        (_revoked, "revoked_key"),
        (_untrusted, "untrusted_key"),
        (_wrong_key_binding, "untrusted_key"),
        (_unsupported, "unsupported_scheme"),
        (_bad_signature, "invalid_signature"),
        (_wrong_scope, "scope_mismatch"),
        (_unavailable, "verification_unavailable"),
    ],
)
async def test_every_proof_refusal_makes_no_effect(make_gate, reason):
    fixture = make_writeback_fixture()
    proof, trust = _signed(fixture.change_set)
    with pytest.raises(WalletProofRefusedError) as error:
        await _port(fixture, make_gate(proof, trust)).apply(fixture.change_set)
    assert error.value.reason == reason
    assert "sensitive" not in str(error.value)
    assert await _status(fixture) == "new"
    assert (
        not fixture.audit.reservations
        if hasattr(fixture.audit, "reservations")
        else True
    )


async def test_a_failing_gate_and_a_non_result_refuse_before_effect():
    fixture = make_writeback_fixture()

    class _Raises:
        async def verify(self, change_set):
            raise RuntimeError("down")

    class _NotAResult:
        async def verify(self, change_set):
            return {"outcome": "verified"}

    for gate, reason in (
        (_Raises(), "verification_unavailable"),
        (_NotAResult(), "missing_signature"),
    ):
        with pytest.raises(WalletProofRefusedError) as error:
            await _port(fixture, gate).apply(fixture.change_set)
        assert error.value.reason == reason
    assert await _status(fixture) == "new"
