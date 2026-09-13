"""The governed client against a local server: retries, timeouts, TLS, logs, bodies."""

from __future__ import annotations

import logging
import ssl
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

from agent_connector_sdk.adapters.mcp_tool_paging import next_position
from agent_connector_sdk.auth.static import BearerAuth
from agent_connector_sdk.http.bodies import (
    DEFAULT_MAX_RESPONSE_BYTES,
    aiter_bounded,
    aread_bounded,
    iter_bounded,
    read_bounded,
)
from agent_connector_sdk.http.client import (
    HTTP_LOGGER_NAME,
    create_async_http_client,
    create_http_client,
    default_ssl_context,
)
from agent_connector_sdk.http.errors import (
    HttpProblemError,
    HttpRateLimitedError,
    ResponseTooLargeError,
    RetriesExhaustedError,
    TlsVerificationError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from agent_connector_sdk.http.options import DEFAULT_TIMEOUT_SECONDS, HttpClientOptions
from agent_connector_sdk.http.pagination import (
    ToolPage,
    cursor_target,
    next_link_cursor,
    preset_pagination,
)
from agent_connector_sdk.http.problems import PROBLEM_JSON
from agent_connector_sdk.http.responses import (
    ERROR_BODY_BYTES,
    aensure_success,
    arequest_json,
    ensure_success,
    request_json,
)
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.http.transport import AsyncGovernedTransport, GovernedTransport
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.testing.certificates import (
    CertificateSet,
    issue_test_certificates,
)
from agent_connector_sdk.testing.http_server import (
    ReceivedRequest,
    ScriptedHttpServer,
    ScriptedResponse,
)
from agent_connector_sdk.tls.profile import ResolvedTLSProfile
from agent_connector_sdk.tls.resolve import resolve_tls_profile

_FAST = RetryPolicy(backoff_base=0.01, max_backoff=0.02)
_JSON = {"Content-Type": "application/json"}
#: Synthetic user information for URLs that must be rejected or redacted.
_USERINFO = ":".join(("user", "pw"))


def _client(
    base_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    tls: ResolvedTLSProfile | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.Client:
    options = HttpClientOptions(
        base_url=base_url, retry=_FAST, timeout=timeout, tls=tls, auth=auth
    )
    return create_http_client(options)


def test_options_fail_closed(caplog: pytest.LogCaptureFixture) -> None:
    rejected = [
        {"base_url": "ftp://api.example.invalid"},
        {"base_url": f"https://{_USERINFO}@api.example.invalid"},
        {"base_url": "https://api.example.invalid", "timeout": float("inf")},
        {"base_url": "https://api.example.invalid", "timeout": httpx.Timeout(None)},
        {
            "base_url": "https://api.example.invalid",
            "headers": {"Authorization": "Bearer x"},
        },
        {"base_url": "http://api.example.invalid"},
    ]
    for arguments in rejected:
        with pytest.raises(ValueError):
            HttpClientOptions(**arguments)
    caplog.set_level(logging.WARNING, logger=HTTP_LOGGER_NAME)
    options = HttpClientOptions(
        base_url="http://api.example.invalid", allow_plaintext=True
    )
    create_http_client(options).close()
    assert "plaintext HTTP" in caplog.text
    assert (
        HttpClientOptions(base_url="http://127.0.0.1:1").timeout
        == DEFAULT_TIMEOUT_SECONDS
    )
    assert default_ssl_context().minimum_version == ssl.TLSVersion.TLSv1_2


def test_retries_rate_limits_and_success() -> None:
    script = (
        ScriptedResponse(status=503),
        ScriptedResponse(status=429, headers={"Retry-After": "0"}),
        ScriptedResponse(body=b'{"ok": true}', headers=_JSON),
    )
    with ScriptedHttpServer(*script) as server, _client(server.base_url) as client:
        assert request_json(client, "GET", "/items", params={"page": 1}) == {"ok": True}
    assert [request.method for request in server.requests] == ["GET", "GET", "GET"]
    assert isinstance(server.requests[0], ReceivedRequest)
    assert server.requests[0].headers["user-agent"].startswith("agent-connector-sdk/")


def test_non_idempotent_rate_limit_is_raised_not_retried() -> None:
    limited = ScriptedResponse(status=429, headers={"Retry-After": "5"})
    server = ScriptedHttpServer(limited)
    with (
        server,
        _client(server.base_url) as client,
        pytest.raises(HttpRateLimitedError) as raised,
    ):
        request_json(client, "POST", "/items", json={"a": 1})
    assert raised.value.retry_after == 5.0 and len(server.requests) == 1


def test_retries_exhausted_on_status_returns_last_problem() -> None:
    busy = [ScriptedResponse(status=503) for _ in range(3)]
    server = ScriptedHttpServer(*busy)
    with (
        server,
        _client(server.base_url) as client,
        pytest.raises(HttpProblemError) as raised,
    ):
        request_json(client, "GET", "/items")
    assert raised.value.problem.status == 503 and len(server.requests) == 3


def test_timeouts() -> None:
    slow = ScriptedResponse(delay=0.5)
    server = ScriptedHttpServer(slow, slow, slow, slow)
    with server, _client(server.base_url, timeout=0.1) as client:
        with pytest.raises(UpstreamTimeoutError):
            client.post("/items")
        with pytest.raises(RetriesExhaustedError) as raised:
            client.get("/items")
    assert raised.value.problem.extensions["attempts"] == 3
    assert isinstance(raised.value.__cause__, httpx.TimeoutException)


def test_unreachable_upstream() -> None:
    with ScriptedHttpServer() as server:
        base_url = server.base_url
    options = HttpClientOptions(base_url=base_url, retry=RetryPolicy(max_attempts=1))
    with create_http_client(options) as client, pytest.raises(UpstreamUnavailableError):
        client.get("/items")


@pytest.fixture(scope="module")
def certificates() -> CertificateSet:
    return issue_test_certificates()


def test_tls_verification(certificates: CertificateSet, tmp_path: Path) -> None:
    context = certificates.server_context(tmp_path)
    ok = ScriptedResponse(body=b"[]", headers=_JSON)
    with ScriptedHttpServer(ok, ssl_context=context) as server:
        with _client(server.base_url) as untrusted, pytest.raises(TlsVerificationError):
            untrusted.get("/items")
        assert server.requests == []
        profile = resolve_tls_profile(
            "demo", profile={"ca_bundle_pem": certificates.ca_pem}
        )
        with _client(server.base_url, tls=profile) as trusted:
            assert request_json(trusted, "GET", "/items") == []
        profile.cleanup()


def test_request_logs_redact_secrets(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=HTTP_LOGGER_NAME)
    server = ScriptedHttpServer(ScriptedResponse())
    auth = BearerAuth("bearer-secret-value")
    with server, _client(server.base_url, auth=auth) as client:
        client.get(
            "/items", params={"private_token": "query-secret-value", "page": "2"}
        )
    assert server.requests[0].headers["authorization"] == "Bearer bearer-secret-value"
    assert "secret-value" not in caplog.text
    record = caplog.records[-1]
    fields = record.__dict__["http"]
    assert fields["url"].endswith("?private_token=REDACTED&page=2")
    assert fields["result"] == 200


def _stream_response(
    chunks: list[bytes], headers: dict[str, str] | None = None
) -> httpx.Response:
    request = httpx.Request("GET", "https://api.example.invalid/blob")
    return httpx.Response(
        200, headers=headers, stream=httpx.ByteStream(b"".join(chunks)), request=request
    )


def test_bounded_bodies() -> None:
    declared = _stream_response([b"x" * 10], {"Content-Length": "10"})
    with pytest.raises(ResponseTooLargeError):
        read_bounded(declared, 5)

    def chunks() -> Iterator[bytes]:
        yield from (b"abc", b"def")

    request = httpx.Request("GET", "https://api.example.invalid/blob")
    streamed = httpx.Response(200, content=chunks(), request=request)
    with pytest.raises(ResponseTooLargeError) as raised:
        list(iter_bounded(streamed, 4))
    assert raised.value.problem.extensions["max_bytes"] == 4
    assert read_bounded(_stream_response([b"abc"])) == b"abc"
    assert DEFAULT_MAX_RESPONSE_BYTES > ERROR_BODY_BYTES


def test_success_checks_and_json_errors() -> None:
    problem = b'{"type": "https://e.invalid/gone", "title": "Gone"}'
    script = (
        ScriptedResponse(
            status=410, body=problem, headers={"Content-Type": PROBLEM_JSON}
        ),
        ScriptedResponse(body=b"not json"),
        ScriptedResponse(status=204),
    )
    with ScriptedHttpServer(*script) as server, _client(server.base_url) as client:
        with (
            client.stream("GET", "/gone") as response,
            pytest.raises(HttpProblemError) as raised,
        ):
            ensure_success(response)
        assert raised.value.problem.title == "Gone"
        with pytest.raises(HttpProblemError, match="not valid JSON"):
            request_json(client, "GET", "/text")
        assert request_json(client, "DELETE", "/items/1") is None


async def test_async_client_paths() -> None:
    script = (
        ScriptedResponse(status=502),
        ScriptedResponse(body=b'{"n": 1}', headers=_JSON),
        ScriptedResponse(status=404),
        ScriptedResponse(body=b"0123456789"),
    )
    with ScriptedHttpServer(*script) as server:
        options = HttpClientOptions(base_url=server.base_url, retry=_FAST)
        async with create_async_http_client(options) as client:
            assert await arequest_json(client, "GET", "/n") == {"n": 1}
            async with client.stream("GET", "/missing") as response:
                with pytest.raises(HttpProblemError):
                    await aensure_success(response)
            async with client.stream("GET", "/blob") as response:
                with pytest.raises(ResponseTooLargeError):
                    await aread_bounded(response, 4)


async def test_async_bounded_iteration() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for chunk in (b"ab", b"cd"):
            yield chunk

    request = httpx.Request("GET", "https://api.example.invalid/blob")
    response = httpx.Response(200, content=chunks(), request=request)
    assert [chunk async for chunk in aiter_bounded(response, 4)] == [b"ab", b"cd"]


def test_sync_transport_honours_retry_after_and_closes_discarded() -> None:
    answers = iter(
        [httpx.Response(503, headers={"Retry-After": "2"}), httpx.Response(200)]
    )
    slept: list[float] = []
    transport = GovernedTransport(
        httpx.MockTransport(lambda request: next(answers)),
        policy=RetryPolicy(jitter=False),
        logger=logging.getLogger("test.transport"),
        sleep=slept.append,
    )
    with httpx.Client(transport=transport) as client:
        assert client.get("https://api.example.invalid/x").status_code == 200
    assert slept == [2.0]


async def test_async_transport_retries_errors() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200)

    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    transport = AsyncGovernedTransport(
        httpx.MockTransport(handler),
        policy=RetryPolicy(jitter=False),
        logger=logging.getLogger("test.transport"),
        sleep=sleep,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await client.post("https://api.example.invalid/x")).status_code == 200
    assert calls == ["POST", "POST"] and slept == [0.5]


def test_tool_pages_feed_the_mcp_tool_modes() -> None:
    base = {"server": "demo", "tool": "list_items"}
    cursor = ToolPreset.from_mapping(
        "c", {**base, **preset_pagination("cursor", cursor_param="cursor")}
    )
    page = ToolPage.from_cursor([{"id": 1}], "next-token")
    result = page.model_dump()
    assert next_position(cursor, {}, result=result, raw=[{"id": 1}]) == {
        "cursor": "next-token"
    }
    last = ToolPage.from_cursor([{"id": 2}], None).model_dump()
    assert (
        next_position(cursor, {"cursor": "next-token"}, result=last, raw=[{"id": 2}])
        is None
    )
    offset = ToolPreset.from_mapping(
        "o",
        {
            **base,
            **preset_pagination(
                "offset", page_param="offset", page_size_param="limit", page_size=2
            ),
        },
    )
    window = ToolPage.from_window([{"id": 1}, {"id": 2}], page_size=2, total=5)
    assert window.has_more and window.total == 5
    assert next_position(
        offset, {"offset": 0}, result=window.model_dump(), raw=[{"id": 1}, {"id": 2}]
    ) == {"offset": 2}
    numbered = ToolPreset.from_mapping(
        "p", {**base, **preset_pagination("page", page_param="page")}
    )
    assert numbered.page_kind == "number"


def test_link_cursors_stay_on_origin() -> None:
    base_url = "https://api.example.invalid/v4"
    request = httpx.Request("GET", f"{base_url}/items")
    linked = httpx.Response(
        200,
        headers={"Link": '<https://api.example.invalid/v4/items?page=2>; rel="next"'},
        request=request,
    )
    cursor = next_link_cursor(linked, base_url=base_url)
    assert (
        cursor == "/v4/items?page=2"
        and cursor_target(cursor, base_url=base_url) == cursor
    )
    assert (
        next_link_cursor(httpx.Response(200, request=request), base_url=base_url)
        is None
    )
    foreign = httpx.Response(
        200,
        headers={"Link": '<https://evil.example.invalid/x>; rel="next"'},
        request=request,
    )
    with pytest.raises(HttpProblemError):
        next_link_cursor(foreign, base_url=base_url)
    for bad in ("https://evil.example.invalid/x", "//evil.example.invalid/x", "items"):
        with pytest.raises(HttpProblemError):
            cursor_target(bad, base_url=base_url)
