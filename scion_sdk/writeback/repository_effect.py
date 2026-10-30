"""Closed, byte-exact repository write intent; this does not grant authority."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Literal

from epistemic_graph.generated.write_back import SourceChangeSet
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from scion_sdk.ports.audit_reservation import AuditReservation
from scion_sdk.writeback._contract_json import _decode_contract_json

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class _VersionedModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1]

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("unsupported schema version")
        return value


def _check_repository_path(path: str) -> None:
    try:
        path.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("path is not valid UTF-8") from exc
    if (
        path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or "%" in path
        or ":" in path.split("/", 1)[0]
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError("unsafe repository path")


class RepositorySourceEffectIntent(_VersionedModel):
    """An exact regular-file effect bound to a provider-specific contract."""

    repository_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    base_revision: str
    expected_file_digest: str | None
    expected_executable: StrictBool | None
    action: Literal["create", "update"]
    payload_base64: str
    payload_sha256: str
    payload_size: StrictInt = Field(ge=0)
    executable: StrictBool
    adapter_contract_digest: str

    @model_validator(mode="after")
    def validate_intent(self) -> RepositorySourceEffectIntent:
        if not _REVISION.fullmatch(self.base_revision):
            raise ValueError("base revision must be a complete immutable Git object ID")
        for value in (self.payload_sha256, self.adapter_contract_digest):
            if not _DIGEST.fullmatch(value):
                raise ValueError("invalid SHA-256 digest")
        self._check_action_claims()
        self._check_payload()
        _check_repository_path(self.relative_path)
        return self

    def _check_action_claims(self) -> None:
        if self.action == "create":
            if (
                self.expected_file_digest is not None
                or self.expected_executable is not None
            ):
                raise ValueError("creation cannot claim an existing file")
        elif (
            self.expected_file_digest is None
            or not _DIGEST.fullmatch(self.expected_file_digest)
            or self.expected_executable is None
        ):
            raise ValueError("update requires existing file digest and mode")

    def _check_payload(self) -> None:
        try:
            raw = base64.b64decode(self.payload_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64 payload") from exc
        if base64.b64encode(raw).decode("ascii") != self.payload_base64:
            raise ValueError("payload must use canonical padded base64")
        if (
            len(raw) != self.payload_size
            or hashlib.sha256(raw).hexdigest() != self.payload_sha256
        ):
            raise ValueError("payload digest or size mismatch")

    def require_readback(self, data: bytes, executable: bool) -> None:
        """Compare an independently fetched file to the exact approved bytes and mode."""
        if type(executable) is not bool or executable != self.executable:
            raise ValueError("readback file mode mismatch")
        if (
            len(data) != self.payload_size
            or hashlib.sha256(data).hexdigest() != self.payload_sha256
            or base64.b64encode(data).decode("ascii") != self.payload_base64
        ):
            raise ValueError("readback bytes do not match approved payload")

    def require_payload_limit(self, limit: int) -> None:
        """Enforce the limit supplied by trusted provider configuration."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("invalid trusted payload limit")
        if self.payload_size > limit:
            raise ValueError("payload exceeds trusted provider limit")


class RepositorySourceEffectRequest(_VersionedModel):
    """An intent joined to the existing generated graph change set."""

    change_set: SourceChangeSet
    intent: RepositorySourceEffectIntent

    @classmethod
    def from_wire_json(
        cls, data: bytes, *, max_payload_size: int
    ) -> RepositorySourceEffectRequest:
        """Parse one bounded JSON request, refusing duplicate keys at any depth."""
        if (
            isinstance(max_payload_size, bool)
            or not isinstance(max_payload_size, int)
            or max_payload_size < 0
        ):
            raise ValueError("invalid trusted payload limit")
        # Account for base64 expansion and bounded protocol metadata before parsing.
        if len(data) > 4 * ((max_payload_size + 2) // 3) + 65536:
            raise ValueError("repository request exceeds trusted limit")

        parsed = _decode_contract_json(data)
        request = cls.model_validate(parsed)
        request.intent.require_payload_limit(max_payload_size)
        return request

    @model_validator(mode="after")
    def validate_binding(self) -> RepositorySourceEffectRequest:
        change = self.change_set
        # Nested Pydantic instances can be constructed with unchecked model_copy.
        # Revalidate before using their values as an effect binding.
        RepositorySourceEffectIntent.model_validate(self.intent.model_dump())
        if (
            json.dumps(
                change.desired_patch,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            != json.dumps(
                {"repository_effect": self.intent.model_dump(mode="json")},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            or change.field_scope != ["repository_effect"]
            or set(change.field_provenance) != {"repository_effect"}
            or change.entity_id != self.intent.repository_id
            or change.base_source_version != self.intent.base_revision
            or change.change_set_digest != change.canonical_digest()
        ):
            raise ValueError("repository intent does not match canonical change set")
        return self


class RepositorySourceEffectReceipt(_VersionedModel):
    """Stable evidence fields for a provider effect with independent readback.

    Constructing this model does not establish an effect; a successful receipt
    must also be bound to the durable graph attempt by the transport.
    """

    tenant_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    source_instance_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    base_revision: str
    change_set_id: str = Field(min_length=1)
    change_set_digest: str
    idempotency_key: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    approval_decision_digest: str
    audit_reservation_id: str = Field(min_length=1)
    adapter_contract_digest: str
    effect_revision: str
    readback_sha256: str
    readback_size: StrictInt = Field(ge=0)
    executable: StrictBool

    @model_validator(mode="after")
    def validate_receipt(self) -> RepositorySourceEffectReceipt:
        if not _REVISION.fullmatch(self.base_revision) or not _REVISION.fullmatch(
            self.effect_revision
        ):
            raise ValueError(
                "receipt revisions must be complete immutable Git object IDs"
            )
        if not all(
            _DIGEST.fullmatch(value)
            for value in (
                self.change_set_digest,
                self.approval_decision_digest,
                self.adapter_contract_digest,
                self.readback_sha256,
            )
        ):
            raise ValueError("invalid receipt digest")
        return self

    def require_binding(
        self, request: RepositorySourceEffectRequest, reservation: AuditReservation
    ) -> None:
        """Verify every receipt field derivable from the approved request."""
        type(self).model_validate(self.model_dump())
        request = RepositorySourceEffectRequest.model_validate(request.model_dump())
        change = request.change_set
        intent = request.intent
        expected = (
            change.tenant_id,
            change.actor,
            change.connector_id,
            change.source_instance_id,
            intent.repository_id,
            intent.target_ref,
            intent.relative_path,
            intent.base_revision,
            change.change_set_id,
            change.change_set_digest,
            change.idempotency_key,
            change.authorization.authorization_ref,
            change.authorization.decision_digest,
            reservation.reservation_id,
            intent.adapter_contract_digest,
            intent.payload_sha256,
            intent.payload_size,
            intent.executable,
        )
        actual = (
            self.tenant_id,
            self.actor,
            self.connector_id,
            self.source_instance_id,
            self.repository_id,
            self.target_ref,
            self.relative_path,
            self.base_revision,
            self.change_set_id,
            self.change_set_digest,
            self.idempotency_key,
            self.approval_ref,
            self.approval_decision_digest,
            self.audit_reservation_id,
            self.adapter_contract_digest,
            self.readback_sha256,
            self.readback_size,
            self.executable,
        )
        if (
            actual != expected
            or not reservation.reservation_id.strip()
            or reservation.effect_key != change.idempotency_key
            or reservation.change_set_digest != change.change_set_digest
        ):
            raise ValueError("receipt binding mismatch")

    def receipt_digest(self) -> str:
        """Hash the stable receipt projection described in the write-back plan."""
        data = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(data).hexdigest()
