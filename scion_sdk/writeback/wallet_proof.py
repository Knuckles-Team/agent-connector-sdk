"""Domain-separated wallet proof verification; proof is not authorization."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from scion_sdk.writeback._contract_json import _decode_contract_json

_MAX_JSON_INTEGER = 2**53 - 1
_SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class WalletProofRequest(BaseModel):
    """Closed Ed25519 proof input; the key is resolved independently."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    wallet_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    key_id: str = Field(min_length=1)
    plan_digest: str
    change_set_digest: str
    idempotency_key: str = Field(min_length=1)
    scheme: str = Field(min_length=1)
    nonce: str = Field(min_length=1)
    issued_at: StrictInt = Field(ge=0, le=_MAX_JSON_INTEGER)
    expires_at: StrictInt = Field(ge=0, le=_MAX_JSON_INTEGER)
    signature: str

    @field_validator(
        "tenant_id",
        "actor_id",
        "connector_id",
        "operation_id",
        "account_id",
        "wallet_id",
        "network_id",
        "key_id",
        "idempotency_key",
        "scheme",
        "nonce",
    )
    @classmethod
    def identity_is_bounded_utf8(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("invalid UTF-8 identity") from exc
        if not encoded or len(encoded) > 4096:
            raise ValueError("invalid identity size")
        return value

    @field_validator("plan_digest", "change_set_digest")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("invalid digest")
        return value

    @field_validator("signature")
    @classmethod
    def signature_is_canonical(cls, value: str) -> str:
        if not _SIGNATURE.fullmatch(value):
            raise ValueError("invalid signature encoding")
        try:
            raw = base64.b64decode(value + "==", altchars=b"-_", validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid signature encoding") from exc
        if (
            len(raw) != 64
            or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value
        ):
            raise ValueError("invalid signature encoding")
        return value

    @classmethod
    def from_wire_json(cls, data: bytes) -> WalletProofRequest:
        """Parse bounded proof JSON without accepting duplicate members."""
        if len(data) > 65536:
            raise ValueError("wallet proof exceeds size limit")

        parsed = _decode_contract_json(data)
        return cls.model_validate(parsed)

    def signed_bytes(self) -> bytes:
        """Serialize the fixed ASCII-keyed string/integer profile of RFC 8785."""
        value = self.model_dump(exclude={"signature"})
        # This profile contains only ASCII property names, strings and exact
        # nonnegative integers, so Python's compact sorted JSON matches JCS.
        return b"SDK-WALLET-INTENT\x001\x00" + json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class WalletProofBinding:
    """Identity supplied by authenticated context and the durable change set."""

    tenant_id: str
    actor_id: str
    connector_id: str
    operation_id: str
    account_id: str
    wallet_id: str
    network_id: str
    key_id: str
    plan_digest: str
    change_set_digest: str
    change_set_id: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class WalletKeyTrust:
    """A current key binding supplied by an authenticated trust authority."""

    binding: WalletProofBinding
    public_key: bytes
    signer_ref: str
    trust_revision: str
    valid_from: int
    valid_until: int
    revoked: bool


class WalletKeyResolver(Protocol):
    async def resolve(self, binding: WalletProofBinding) -> WalletKeyTrust | None:
        """Resolve the binding from the current trusted account authority."""
        ...


class WalletProofGate(Protocol):
    """Supplies the verified proof fact for one durable change set.

    The gate pairs the request received with the call, the authenticated
    binding and a verifier. It returns a fact only; approval, confirmation and
    audit reservation remain independent checks in ``GovernedWriteBack.apply``.
    """

    async def verify(self, change_set: Any) -> WalletProofResult:
        """Return the verification fact for this exact change set."""
        ...


class WalletProofResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["verified", "refused"]
    reason: str
    payload_digest: str | None = None
    signer_ref: str | None = None
    trust_revision: str | None = None
    valid_from: StrictInt | None = None
    valid_until: StrictInt | None = None


class WalletSignatureVerifier:
    """Verify a proof fact; approval, confirmation and effect fencing remain separate."""

    def __init__(self, resolver: WalletKeyResolver, *, max_lifetime: int = 300) -> None:
        if type(max_lifetime) is not int or not 0 < max_lifetime <= 300:
            raise ValueError("invalid proof lifetime")
        self._resolver = resolver
        self._max_lifetime = max_lifetime

    async def verify(
        self, request: WalletProofRequest, binding: WalletProofBinding, *, now: int
    ) -> WalletProofResult:
        """Verify an exact bound request against the current trusted key."""
        try:
            request = WalletProofRequest.model_validate(request.model_dump())
            payload = request.signed_bytes()
        except (ValueError, TypeError, UnicodeError):
            return WalletProofResult(outcome="refused", reason="invalid_payload")
        if request.scheme != "ed25519_jcs":
            return WalletProofResult(outcome="refused", reason="unsupported_scheme")
        if type(now) is not int or not (
            request.issued_at <= now < request.expires_at
            and request.expires_at - request.issued_at <= self._max_lifetime
        ):
            return WalletProofResult(outcome="refused", reason="expired")
        fields = (
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
        if any(getattr(request, name) != getattr(binding, name) for name in fields) or (
            request.nonce != binding.change_set_id
        ):
            return WalletProofResult(outcome="refused", reason="scope_mismatch")
        try:
            trusted = await self._resolver.resolve(binding)
        except Exception:
            return WalletProofResult(
                outcome="refused", reason="verification_unavailable"
            )
        if trusted is None or trusted.binding != binding:
            return WalletProofResult(outcome="refused", reason="untrusted_key")
        if trusted.revoked:
            return WalletProofResult(outcome="refused", reason="revoked_key")
        if not (
            trusted.signer_ref
            and trusted.trust_revision
            and len(trusted.public_key) == 32
            and trusted.valid_from <= now < trusted.valid_until
        ):
            return WalletProofResult(
                outcome="refused", reason="verification_unavailable"
            )
        try:
            signature = base64.urlsafe_b64decode(request.signature + "==")
            Ed25519PublicKey.from_public_bytes(trusted.public_key).verify(
                signature, payload
            )
        except (ValueError, InvalidSignature):
            return WalletProofResult(outcome="refused", reason="invalid_signature")
        return WalletProofResult(
            outcome="verified",
            reason="verified",
            payload_digest=hashlib.sha256(payload).hexdigest(),
            signer_ref=trusted.signer_ref,
            trust_revision=trusted.trust_revision,
            valid_from=max(request.issued_at, trusted.valid_from),
            valid_until=min(request.expires_at, trusted.valid_until),
        )
