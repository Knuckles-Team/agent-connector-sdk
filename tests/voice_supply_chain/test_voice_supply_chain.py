"""Voice-model manifest validation and the license-gated promotion handoff."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_connector_sdk.voice_supply_chain import license_registry as lr
from agent_connector_sdk.voice_supply_chain import store
from agent_connector_sdk.voice_supply_chain.manifest import (
    VoiceLicenseDecision,
    VoiceManifestStatus,
    VoiceModelManifest,
)

REV, SHA = "a" * 40, "b" * 64
OK = "counsel@example.invalid"


pytestmark = [
    pytest.mark.spec("SDK-SOURCE-INGEST-R804"),
]


@pytest.fixture(autouse=True)
def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)


def _manifest(**over: object) -> VoiceModelManifest:
    fields: dict[str, object] = {
        "manifest_id": SHA,
        "source_host": "huggingface.co",
        "source_repository": "rhasspy/piper-voices",
        "source_revision": REV,
        "source_path": "en/lessac.onnx",
        "source_url": "https://huggingface.co/x",
        "byte_length": 1,
        "sha256": SHA,
        "status": VoiceManifestStatus.VERIFIED,
    }
    fields.update(over)
    return VoiceModelManifest(**fields)


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"source_revision": "main"}, "commit SHA"),
        ({"source_revision": "a" * 39}, "commit SHA"),
        ({"sha256": "not-hex"}, "sha256"),
    ],
)
def test_manifest_requires_immutable_pin_and_valid_digest(over, match):
    with pytest.raises(ValidationError, match=match):
        _manifest(**over)


def test_manifest_normalizes_digest_case_and_defaults_are_fail_closed():
    assert _manifest(sha256="B" * 64).sha256 == SHA
    assert VoiceLicenseDecision(asset_manifest_id=SHA).counsel_decision == "pending"
    with pytest.raises(ValidationError):
        VoiceLicenseDecision(asset_manifest_id=SHA, counsel_decision="maybe")


@pytest.mark.parametrize(
    ("decision", "status", "ready", "reason"),
    [
        (None, VoiceManifestStatus.VERIFIED, False, "no license decision"),
        ({}, VoiceManifestStatus.VERIFIED, False, "pending"),
        (
            {"counsel_decision": "approved"},
            VoiceManifestStatus.VERIFIED,
            False,
            "reviewer",
        ),
        (
            {"counsel_decision": "approved", "reviewer": OK},
            VoiceManifestStatus.QUARANTINED,
            False,
            "quarantined",
        ),
        (
            {"counsel_decision": "approved", "reviewer": OK},
            VoiceManifestStatus.VERIFIED,
            True,
            "",
        ),
        (
            {"is_gpl_or_copyleft_flagged": True, "declared_license": "GPL-3.0"},
            VoiceManifestStatus.VERIFIED,
            False,
            "",
        ),
    ],
)
def test_promotion_handoff_requires_approved_license_and_verified_asset(
    decision, status, ready, reason
):
    if decision is not None:
        lr.record_license_decision(
            VoiceLicenseDecision(asset_manifest_id=SHA, **decision)
        )
    got_ready, got_reason = lr.is_ready_for_promotion_handoff(_manifest(status=status))
    assert got_ready is ready
    assert reason in got_reason


def test_mark_verified_persists_and_refuses_rejected():
    quarantined = _manifest(status=VoiceManifestStatus.QUARANTINED)
    (store.manifest_index_dir() / f"{SHA}.json").write_text(
        quarantined.model_dump_json()
    )
    assert lr.mark_verified(quarantined).status == VoiceManifestStatus.VERIFIED
    with pytest.raises(ValueError, match="REJECTED"):
        lr.mark_verified(_manifest(status=VoiceManifestStatus.REJECTED))
