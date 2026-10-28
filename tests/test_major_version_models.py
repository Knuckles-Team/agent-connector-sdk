"""Transition and receipt shape only; these tests do not authorize rollout."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_connector_sdk.testing.major_version import (
    MajorVersionTransition,
    PackageCompatibilityReceipt,
    PackageInventoryEntry,
    PackageInventorySnapshot,
    check_receipt_binding,
)


def _snapshot(entries: tuple[PackageInventoryEntry, ...]) -> PackageInventorySnapshot:
    payload = [entry.model_dump(mode="json") for entry in entries]
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return PackageInventorySnapshot(
        entries=entries, inventory_digest=hashlib.sha256(encoded).hexdigest()
    )


def _entry(package: str = "alpha") -> PackageInventoryEntry:
    return PackageInventoryEntry(
        package_id=package,
        repository_id="org/repo",
        source_commit="a" * 40,
        current_pin="1.2.3",
        preimage_digest="b" * 64,
    )


def _values() -> tuple[
    MajorVersionTransition, PackageInventorySnapshot, PackageCompatibilityReceipt
]:
    entry = _entry()
    inventory = _snapshot((entry,))
    transition = MajorVersionTransition(
        transition_id="transition",
        distribution="scion-sdk",
        old_pin="1.2.3",
        target_pin="2.0.0",
        target_artifact_digest="c" * 64,
        inventory_digest=inventory.inventory_digest,
    )
    receipt = PackageCompatibilityReceipt(
        transition_id=transition.transition_id,
        inventory_digest=inventory.inventory_digest,
        package_id=entry.package_id,
        repository_id=entry.repository_id,
        source_commit=entry.source_commit,
        old_pin=transition.old_pin,
        target_pin=transition.target_pin,
        preimage_digest=entry.preimage_digest,
        target_artifact_digest=transition.target_artifact_digest,
        suite="suite",
        run="run",
        completed_at=datetime(2026, 10, 27, tzinfo=UTC),
        outcome="passed",
    )
    return transition, inventory, receipt


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R007.1")
def test_inventory_digest_and_major_transition_are_checked() -> None:
    transition, inventory, _ = _values()
    assert (
        MajorVersionTransition.model_validate_json(transition.model_dump_json())
        == transition
    )
    assert (
        PackageInventorySnapshot.model_validate_json(inventory.model_dump_json())
        == inventory
    )
    for entries in ((_entry(), _entry()), (_entry("z"), _entry("a"))):
        with pytest.raises(ValidationError):
            _snapshot(entries)
    with pytest.raises(ValidationError):
        PackageInventorySnapshot(entries=inventory.entries, inventory_digest="f" * 64)
    with pytest.raises(ValidationError):
        MajorVersionTransition.model_validate(
            {**transition.model_dump(), "target_pin": "1.9.0"}
        )
    with pytest.raises(ValidationError):
        PackageInventoryEntry.model_validate(
            {**_entry().model_dump(), "package_id": ""}
        )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R007.1")
def test_receipt_is_immutable_and_rejects_mismatched_bindings() -> None:
    transition, inventory, receipt = _values()
    check_receipt_binding(transition, inventory, receipt)
    with pytest.raises(ValidationError):
        receipt.outcome = "failed"  # type: ignore[misc]
    for field, value in (
        ("transition_id", "other"),
        ("inventory_digest", "d" * 64),
        ("package_id", "other"),
        ("repository_id", "other"),
        ("source_commit", "d" * 40),
        ("old_pin", "1.0.0"),
        ("target_pin", "3.0.0"),
        ("preimage_digest", "d" * 64),
        ("target_artifact_digest", "d" * 64),
    ):
        altered = PackageCompatibilityReceipt.model_validate(
            {**receipt.model_dump(), field: value}
        )
        with pytest.raises(ValueError):
            check_receipt_binding(transition, inventory, altered)
