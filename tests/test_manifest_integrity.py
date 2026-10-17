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


def _b64url(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_release_signature_verifies_only_a_trusted_default_signer():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = Ed25519PrivateKey.generate()
    public = _b64url(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    digest = "a" * 64
    (signer,) = mi.DEFAULT_TRUSTED_SIGNERS
    signature = _b64url(key.sign(f"{signer}:{digest}".encode("ascii")))
    common = {"signer_id": signer, "algorithm": "ed25519", "public_key": public}
    assert mi.verify_release_signature(
        digest, signature, trusted_public_keys=(public,), **common
    )
    assert not mi.verify_release_signature(
        digest, signature, trusted_public_keys=(), **common
    )
    assert not mi.verify_release_signature(
        "b" * 64, signature, trusted_public_keys=(public,), **common
    )
    placeholder = mi.unsigned_release_placeholder()
    assert placeholder.signer_id == mi.UNSIGNED_SIGNER_ID
    assert mi.UNSIGNED_SIGNER_ID not in mi.DEFAULT_TRUSTED_SIGNERS
    with pytest.raises(mi.ReleaseSigningError):
        placeholder.sign(digest)


def test_trusted_keys_union_the_setting_and_the_rotation_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "rotation.yml"
    ledger.write_text(
        yaml.safe_dump({"rotations": [{"to_public_key": SWAPPED}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONNECTOR_RELEASE_ROTATION_RECORD", str(ledger))
    monkeypatch.setenv("ONTOLOGY_RELEASE_TRUSTED_PUBLIC_KEYS", f" {PINNED} ,")
    assert mi.rotation_record()["rotations"][0]["to_public_key"] == SWAPPED
    assert set(mi.release_trusted_public_keys()) == {PINNED, SWAPPED}
    assert mi.rotation_record(tmp_path / "absent.yml") == {}


def test_lock_entries_are_byte_stable_and_hashes_skip_the_signature(tmp_path):
    path = tmp_path / "ontology.lock"
    mi.update_lock_entry(path, "b/m.yml", "1" * 64, signer="s", metadata={"x": None})
    entries = mi.update_lock_entry(path, "a/m.yml", "2" * 64, triple_count=3)
    assert list(mi.load_lock(path)) == ["a/m.yml", "b/m.yml"] == sorted(entries)
    assert "x" not in entries["b/m.yml"]
    first = path.read_bytes()
    mi.save_lock(path, mi.load_lock(path))
    assert path.read_bytes() == first

    manifest = {"name": "c", "provenance": {"signature": "sig-1"}}
    resigned = {"name": "c", "provenance": {"signature": "sig-2"}}
    assert mi.canonical_manifest_hash(manifest) == mi.canonical_manifest_hash(resigned)
    assert mi.canonical_manifest_hash(manifest) != mi.canonical_manifest_hash(
        {"name": "d", "provenance": {}}
    )
    assert mi.canonical_signed_document_hash(
        {"a": 1, "signature": "x"}
    ) == mi.canonical_signed_document_hash({"a": 1, "signature": "y"})
    with pytest.raises(TypeError):
        mi.canonical_manifest_hash(["not", "a", "mapping"])


def test_commit_sha_is_descriptive_and_fails_soft(tmp_path):
    sha = mi.repository_commit_sha(Path(__file__).resolve().parents[1])
    assert sha is None or len(sha) == 40
    assert mi.repository_commit_sha(tmp_path) is None


def test_canonical_rdf_hash_ignores_triple_order():
    rdflib = pytest.importorskip("rdflib")
    turtle = "@prefix e: <http://e/> . e:a e:p e:b . e:b e:p e:c ."
    reordered = "@prefix e: <http://e/> . e:b e:p e:c . e:a e:p e:b ."
    first = mi.canonical_hash(rdflib.Graph().parse(data=turtle, format="turtle"))
    second = mi.canonical_hash(rdflib.Graph().parse(data=reordered, format="turtle"))
    assert first == second and first[1] == 2
