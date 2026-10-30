"""Bound data for fleet compatibility evidence, without rollout authority."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "MajorVersionTransition",
    "PackageCompatibilityReceipt",
    "PackageInventoryEntry",
    "PackageInventorySnapshot",
    "check_receipt_binding",
]

_ID = Field(min_length=1, max_length=512, pattern=r"^\S(?:.*\S)?$")
_SHA256 = Field(pattern=r"^[0-9a-f]{64}$")
_REVISION = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PIN = Field(pattern=r"^(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,2}$")


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class PackageInventoryEntry(_Strict):
    """A package at one immutable source and dependency-file preimage."""

    package_id: str = _ID
    repository_id: str = _ID
    source_commit: str = _REVISION
    current_pin: str = _PIN
    preimage_digest: str = _SHA256


class PackageInventorySnapshot(_Strict):
    """A sorted, unique inventory and the SHA-256 of its canonical entries."""

    entries: tuple[PackageInventoryEntry, ...] = Field(min_length=1)
    inventory_digest: str = _SHA256

    @model_validator(mode="after")
    def _validate_entries(self) -> PackageInventorySnapshot:
        package_ids = [entry.package_id for entry in self.entries]
        if package_ids != sorted(set(package_ids)):
            raise ValueError("inventory package IDs must be unique and sorted")
        payload = [entry.model_dump(mode="json") for entry in self.entries]
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != self.inventory_digest:
            raise ValueError("inventory digest does not match entries")
        return self


class MajorVersionTransition(_Strict):
    """The exact artifact, pins and inventory of one major upgrade."""

    transition_id: str = _ID
    distribution: str = _ID
    old_pin: str = _PIN
    target_pin: str = _PIN
    target_artifact_digest: str = _SHA256
    inventory_digest: str = _SHA256

    @model_validator(mode="after")
    def _major_upgrade(self) -> MajorVersionTransition:
        if int(self.target_pin.split(".")[0]) <= int(self.old_pin.split(".")[0]):
            raise ValueError("target pin must advance the major version")
        return self


class PackageCompatibilityReceipt(_Strict):
    """One completed suite result bound to a package and transition."""

    transition_id: str = _ID
    inventory_digest: str = _SHA256
    package_id: str = _ID
    repository_id: str = _ID
    source_commit: str = _REVISION
    old_pin: str = _PIN
    target_pin: str = _PIN
    preimage_digest: str = _SHA256
    target_artifact_digest: str = _SHA256
    suite: str = _ID
    run: str = _ID
    completed_at: datetime
    outcome: Literal["passed", "failed"]

    @model_validator(mode="after")
    def _aware_completion(self) -> PackageCompatibilityReceipt:
        if self.completed_at.utcoffset() is None:
            raise ValueError("completion timestamp must include a timezone")
        return self


def check_receipt_binding(
    transition: MajorVersionTransition,
    inventory: PackageInventorySnapshot,
    receipt: PackageCompatibilityReceipt,
) -> None:
    """Refuse a receipt that does not match its transition and inventory entry.

    This validates only binding. It does not prove suite execution, inventory
    completeness, or authorize any package write.
    """
    if transition.inventory_digest != inventory.inventory_digest:
        raise ValueError("transition inventory mismatch")
    entries = {entry.package_id: entry for entry in inventory.entries}
    entry = entries.get(receipt.package_id)
    if entry is None:
        raise ValueError("receipt package not in inventory")
    actual = (
        receipt.transition_id,
        receipt.inventory_digest,
        receipt.repository_id,
        receipt.source_commit,
        receipt.old_pin,
        receipt.target_pin,
        receipt.preimage_digest,
        receipt.target_artifact_digest,
    )
    expected = (
        transition.transition_id,
        transition.inventory_digest,
        entry.repository_id,
        entry.source_commit,
        transition.old_pin,
        transition.target_pin,
        entry.preimage_digest,
        transition.target_artifact_digest,
    )
    if actual != expected or entry.current_pin != transition.old_pin:
        raise ValueError("receipt binding mismatch")
