"""Ed25519 datapoint signing: round trip, tamper detection and fail-closed verify."""

from __future__ import annotations

import base64

import pytest

from scion_sdk import signing

SEED = bytes(range(32))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R901.2")
def test_signature_round_trips_over_canonical_json() -> None:
    public = signing.public_key_b64(SEED)
    signature = signing.sign_datapoint({"b": 2, "a": 1}, SEED)
    assert signing.verify_datapoint({"a": 1, "b": 2}, signature, public)
    assert signing.verify_datapoint('{"a":1,"b":2}', signature, public)


# spec: SCION-CONNECTOR-CONTROL-R901.4
@pytest.mark.parametrize(
    ("datapoint", "signature", "public"),
    [
        ({"a": 2}, "good", "good"),
        ({"a": 1}, "AAAA", "good"),
        ({"a": 1}, "good", signing.public_key_b64(bytes(32))),
        ({"a": 1}, "", "good"),
        ({"a": 1}, "good", "not base64!"),
    ],
)
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R901.5")
def test_any_mismatch_fails_closed(
    datapoint: object, signature: str, public: str
) -> None:
    good_sig = signing.sign_datapoint({"a": 1}, SEED)
    good_pub = signing.public_key_b64(SEED)
    signature = good_sig if signature == "good" else signature
    public = good_pub if public == "good" else public
    assert signing.verify_datapoint(datapoint, signature, public) is False


# spec: SCION-CONNECTOR-CONTROL-R901.4, SCION-CONNECTOR-CONTROL-R901.6
def test_configured_seed_is_used_and_malformed_seed_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(signing.SEED_SETTING, raising=False)
    assert signing.is_configured() is False
    assert signing.verify_datapoint(
        "x", signing.sign_datapoint("x"), signing.public_key_b64()
    )
    monkeypatch.setenv(signing.SEED_SETTING, base64.b64encode(SEED).decode())
    assert signing.is_configured() is True
    assert signing.public_key_b64() == signing.public_key_b64(SEED)
    monkeypatch.setenv(signing.SEED_SETTING, base64.b64encode(b"short").decode())
    with pytest.raises(signing.SigningKeyError):
        signing.sign_datapoint("x")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R901.3")
def test_configured_signing_seed_reads_through_sdk_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real_setting = signing.setting

    def setting(name: str, *args: object, **kwargs: object) -> object:
        calls.append(name)
        return real_setting(name, *args, **kwargs)

    monkeypatch.setattr(signing, "setting", setting)
    monkeypatch.setenv(signing.SEED_SETTING, base64.b64encode(SEED).decode())

    assert signing.public_key_b64() == signing.public_key_b64(SEED)
    assert signing.SEED_SETTING in calls
