"""Governed Requests-only compatibility session."""

from typing import Any

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.models import Response

from agent_connector_sdk.http.client import AirgapViolation
from agent_connector_sdk.http.requests import create_requests_session


class _Adapter(BaseAdapter):
    def __init__(self, *, redirect: bool = False) -> None:
        self.redirect = redirect
        self.calls: list[dict[str, Any]] = []

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> Response:
        self.calls.append({"url": request.url, **kwargs})
        response = Response()
        response.request = request
        response.url = request.url
        response.status_code = 302 if self.redirect else 200
        response._content = b""
        if self.redirect:
            response.headers["Location"] = "https://example.com/escaped"
        return response

    def close(self) -> None:
        pass


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R780.9")
def test_requests_session_default_timeout_verify_and_override() -> None:
    adapter = _Adapter()
    with create_requests_session(headers={"user-agent": "consumer/1"}) as session:
        session.mount("https://", adapter)
        assert session.trust_env is False
        assert session.get("https://example.com/").status_code == 200
        assert adapter.calls[0]["timeout"] == 30.0
        assert adapter.calls[0]["verify"] is True
        assert session.headers["User-Agent"] == "consumer/1"
        with pytest.raises(ValueError, match="TLS verification"):
            session.get("https://example.com/", verify=False)
        prepared = requests.Request("GET", "https://example.com/").prepare()
        with pytest.raises(ValueError, match="TLS verification"):
            session.send(prepared, verify=None)
        with pytest.raises(ValueError, match="timeout"):
            session.send(prepared, timeout=(1, None))
    assert len(adapter.calls) == 1
    with pytest.raises(ValueError, match="credential headers"):
        create_requests_session(headers={"Authorization": "synthetic"})


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R780.9")
def test_requests_session_airgap_blocks_redirect_and_proxy(monkeypatch: Any) -> None:
    monkeypatch.setenv("AIRGAP_MODE", "true")
    adapter = _Adapter(redirect=True)
    with create_requests_session() as session:
        session.mount("https://", adapter)
        with pytest.raises(AirgapViolation):
            session.get("https://127.0.0.1/start")
        assert [call["url"] for call in adapter.calls] == ["https://127.0.0.1/start"]
        session.proxies["https"] = "https://example.com:443"
        with pytest.raises(AirgapViolation):
            session.get("https://127.0.0.1/")
        session.proxies.clear()
        session.trust_env = True
        with pytest.raises(AirgapViolation):
            session.get("https://127.0.0.1/")
    assert len(adapter.calls) == 1
