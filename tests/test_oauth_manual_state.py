"""Manual OAuth completion binds the full callback to the login state."""

from types import SimpleNamespace

import pytest

from scion_sdk.auth.browser import BaseBrowserAuthManager


def manager() -> BaseBrowserAuthManager:
    return BaseBrowserAuthManager(
        client_id="client",
        auth_endpoint="https://idp.example/authorize",
        token_endpoint="https://idp.example/token",
        scopes="openid",
        secret_key="token",
        redirect_host="127.0.0.1",
        redirect_port=56122,
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R046.10")
@pytest.mark.parametrize("tty", [True, False])
def test_manual_callback_requires_redirect_and_matching_state(
    monkeypatch, tty: bool
) -> None:
    auth = manager()
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: tty))
    valid = "http://127.0.0.1:56122/callback?code=accepted&state=expected"
    field = "_prompt_for_manual_code" if tty else "_read_manual_code_file"
    monkeypatch.setattr(auth, field, lambda: valid)
    assert auth._get_authorization_code(None, "expected") == "accepted"
    for invalid in (
        "bare-code",
        "http://127.0.0.1:56122/callback?code=x&state=wrong",
        "http://evil.example/callback?code=x&state=expected",
        "http://127.0.0.1:56122/callback?code=x&state=expected&state=other",
        "http://127.0.0.1:56122/callback?code=x&code=y&state=expected",
        "http://127.0.0.1:56122/callback?code=x&state=expected#fragment",
        "http://127.0.0.1:56122/callback;other?code=x&state=expected",
        "http://127.0.0.1:56122/callback?code=x&state=expected&error=denied",
    ):
        monkeypatch.setattr(auth, field, lambda value=invalid: value)
        with pytest.raises(ValueError, match="manual callback is invalid"):
            auth._get_authorization_code(None, "expected")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R046.10")
def test_login_does_not_exchange_a_raw_manual_code(monkeypatch) -> None:
    auth = manager()
    monkeypatch.setattr(
        auth, "_discover_endpoints", lambda: (auth.auth_endpoint, auth.token_endpoint)
    )
    monkeypatch.setattr(auth, "_start_loopback_server", lambda state: None)
    monkeypatch.setattr(auth, "_announce_authorization", lambda url: None)
    monkeypatch.setattr(auth, "_prompt_for_manual_code", lambda: "raw-code")
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    exchanged = []
    monkeypatch.setattr(
        auth, "_exchange_authorization_code", lambda *args: exchanged.append(args)
    )
    with pytest.raises(ValueError, match="manual callback is invalid"):
        auth.login()
    assert exchanged == []
