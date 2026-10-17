"""Release signing custody: lock-agreeing, versioned, rotation-governed."""

# spec: SDK-CONNECTOR-CONTROL-R650

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_connector_sdk.manifest import integrity as mi

PINNED = "QkigdPNpcUU7x7NcSkwCsUXIQpaFncMQbYSoiSgI2SY"
SWAPPED = "rJhTqqFwZFHnKJxdp2hfRzCX6Cz4mKbocugAxKTdiE4"


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    entries = {
        "agents/c/connector_manifest.yml": {
            "hash": "0" * 64,
            "signing_public_key": PINNED,
            "certification_signing_public_key": PINNED,
        }
    }
    path = tmp_path / "ontology.lock"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return path


def _signer(key: str) -> mi.ReleaseSigner:
    return mi.ReleaseSigner(signer_id=mi.DEFAULT_SIGNER_ID, public_key=key)


@pytest.mark.parametrize(
    ("key", "rotating", "refused"),
    [(PINNED, False, False), (SWAPPED, False, True), (SWAPPED, True, False)],
)
def test_signing_key_must_match_locks_unless_rotating(lock, key, rotating, refused):
    call = lambda: mi.assert_signing_key_matches_locks(  # noqa: E731
        _signer(key), lock_path=lock, rotating=rotating
    )
    if refused:
        with pytest.raises(mi.ReleaseSigningError):
            call()
    else:
        call()


def test_lock_pins_and_missing_lock(lock, tmp_path):
    assert mi.lock_pinned_public_keys(lock) == frozenset({PINNED})
    mi.assert_signing_key_matches_locks(
        _signer(SWAPPED), lock_path=tmp_path / "absent.lock"
    )


def test_publication_refuses_unversioned_custody(lock, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_RELEASE_SIGNING_PRIVATE_KEY_REF", "env://X")
    with pytest.raises(mi.ReleaseSigningError, match="versioned"):
        mi.release_signer_for_publication(lock_path=lock)
    assert "env://" not in mi.DURABLE_SECRET_SCHEMES


def test_rotation_ledger_designates_active_key(tmp_path):
    record = tmp_path / "rotation.yml"
    assert mi.active_release_public_key(record) is None
    rotations = [{"to_public_key": PINNED}, {"to_public_key": SWAPPED}]
    record.write_text(yaml.safe_dump({"rotations": rotations}), encoding="utf-8")
    assert mi.active_release_public_key(record) == SWAPPED
    record.write_text(
        yaml.safe_dump({"rotations": [{"to_public_key": "bad"}]}), encoding="utf-8"
    )
    with pytest.raises(mi.ReleaseSigningError):
        mi.active_release_public_key(record)
