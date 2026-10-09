"""SDK-CONNECTOR-CONTROL-R033: SSRF-checked JSON POST."""

from __future__ import annotations

import httpx
import pytest

from agent_connector_sdk.http.safe_post import (
    NonJsonResponseError,
    SsrfBlockedError,
    safe_post_json,
)


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="http://placeholder.invalid")


def test_disallowed_private_destination_rejected_before_send() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("request must not be sent")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(SsrfBlockedError):
        safe_post_json(client, "http://127.0.0.1:9999/submit", {"a": 1})


def test_allowed_private_host_succeeds_and_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        return httpx.Response(200, json={"ok": True})

    client = _client(httpx.MockTransport(handler))
    result = safe_post_json(
        client,
        "http://127.0.0.1:9999/submit",
        {"a": 1},
        allowed_private_hosts=frozenset({"127.0.0.1"}),
    )
    assert result == {"ok": True}


def test_non_json_response_raises_typed_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NonJsonResponseError):
        safe_post_json(
            client,
            "http://127.0.0.1:9999/submit",
            {},
            allowed_private_hosts=frozenset({"127.0.0.1"}),
        )
