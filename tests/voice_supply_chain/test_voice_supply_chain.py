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


@pytest.mark.spec("SDK-SOURCE-INGEST-R804.6")
def test_thousand_license_decisions_use_one_read_per_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions = [
        VoiceLicenseDecision(
            asset_manifest_id=f"{index:064x}",
            counsel_decision="approved" if index % 2 else "pending",
            reviewer=f"reviewer-{index}",
        )
        for index in range(1000)
    ]
    for decision in decisions:
        lr.record_license_decision(decision)

    original_read_text = Path.read_text
    reads: list[Path] = []

    def counted_read_text(path: Path, *args: object, **kwargs: object) -> str:
        reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)
    for decision in decisions:
        reads.clear()
        assert lr.get_license_decision(decision.asset_manifest_id) == decision
        assert len(reads) == 1
        assert reads[0].name == f"{decision.asset_manifest_id}.license.json"


# spec: SDK-SOURCE-INGEST-R804.4
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R804.1")
def test_manifest_normalizes_digest_case_and_defaults_are_fail_closed():
    assert _manifest(sha256="B" * 64).sha256 == SHA
    assert VoiceLicenseDecision(asset_manifest_id=SHA).counsel_decision == "pending"
    with pytest.raises(ValidationError):
        VoiceLicenseDecision(asset_manifest_id=SHA, counsel_decision="maybe")


# spec: SDK-SOURCE-INGEST-R804.2
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
            {"counsel_decision": "approved", "reviewer": " \t\n"},
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
@pytest.mark.spec("SDK-SOURCE-INGEST-R804.5")
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R804.3")
def test_mark_verified_persists_and_refuses_rejected():
    quarantined = _manifest(status=VoiceManifestStatus.QUARANTINED)
    (store.manifest_index_dir() / f"{SHA}.json").write_text(
        quarantined.model_dump_json()
    )
    assert lr.mark_verified(quarantined).status == VoiceManifestStatus.VERIFIED
    with pytest.raises(ValueError, match="REJECTED"):
        lr.mark_verified(_manifest(status=VoiceManifestStatus.REJECTED))


def test_license_decisions_round_trip_and_absence_is_none():
    assert lr.get_license_decision(SHA) is None
    decision = VoiceLicenseDecision(
        asset_manifest_id=SHA, declared_license="MIT", counsel_decision="approved"
    )
    lr.record_license_decision(decision)
    assert lr.get_license_decision(SHA) == decision


def test_provider_is_piper_only_and_config_manifest_pins_its_digest():
    from agent_connector_sdk.voice_supply_chain.manifest import (
        HF_COMMIT_SHA_LEN,
        VoiceConfigManifest,
        VoiceModelProvider,
    )

    assert len(REV) == HF_COMMIT_SHA_LEN
    assert _manifest().provider is VoiceModelProvider.PIPER
    assert [p.value for p in VoiceModelProvider] == ["piper"]
    config = VoiceConfigManifest(
        manifest_id="c",
        model_manifest_id=SHA,
        sha256=SHA.upper(),
        byte_length=2,
        sample_rate=22_050,
    )
    assert config.sha256 == SHA
    with pytest.raises(ValidationError, match="sha256"):
        VoiceConfigManifest(
            manifest_id="c",
            model_manifest_id=SHA,
            sha256="x",
            byte_length=2,
            sample_rate=22_050,
        )
    with pytest.raises(ValidationError):
        VoiceConfigManifest(
            manifest_id="c",
            model_manifest_id=SHA,
            sha256=SHA,
            byte_length=2,
            sample_rate=0,
        )


@pytest.mark.spec("SDK-SOURCE-INGEST-R804.7")
@pytest.mark.parametrize(
    "bad_id",
    ("../escape", "/tmp/escape", "a/b", "a\\b", ".", "..", "", "x\x00y", "x" * 129),
)
def test_manifest_identifiers_refuse_path_escape_before_file_access(bad_id, tmp_path):
    with pytest.raises(ValidationError):
        _manifest(manifest_id=bad_id)
    with pytest.raises(ValidationError):
        VoiceLicenseDecision(asset_manifest_id=bad_id)
    with pytest.raises(ValueError, match="invalid manifest identifier"):
        lr.get_license_decision(bad_id)
    with pytest.raises(ValueError, match="invalid manifest identifier"):
        lr.mark_verified(_manifest().model_copy(update={"manifest_id": bad_id}))
    forged = VoiceLicenseDecision.model_construct(asset_manifest_id=bad_id)
    with pytest.raises(ValueError, match="invalid manifest identifier"):
        lr.record_license_decision(forged)
    assert not (tmp_path / "voice-models").exists()


@pytest.mark.spec("SDK-SOURCE-INGEST-R804.7")
def test_foreign_license_approval_cannot_authorize_handoff(tmp_path):
    index = store.manifest_index_dir()
    decision = VoiceLicenseDecision(
        asset_manifest_id="another-manifest", counsel_decision="approved", reviewer=OK
    )
    (index / f"{SHA}.license.json").write_text(decision.model_dump_json())

    assert lr.get_license_decision(SHA) is None
    ready, reason = lr.is_ready_for_promotion_handoff(_manifest())
    assert not ready
    assert "no license decision" in reason
