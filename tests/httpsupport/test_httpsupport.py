"""Public behaviour of the fleet HTTP helpers: auth, rate limits, redaction."""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from agent_connector_sdk.httpsupport.auth import (
    AuthHeaderInjector,
    BasicAuth,
    QueryApiKeyAuth,
    TokenAuth,
)
from agent_connector_sdk.httpsupport.rate_limit import (
    RateLimitCapture,
    RateLimitSnapshot,
    backoff_seconds,
    parse_rate_limit,
)
from agent_connector_sdk.httpsupport.redaction import REDACTED, LogRedactor, redact_text

pytestmark = [
    pytest.mark.spec("SDK-SOURCE-INGEST-R802"),
]


@pytest.mark.parametrize(
    ("auth", "headers", "params", "secrets"),
    [
        (AuthHeaderInjector(), {}, {}, []),
        (TokenAuth("t"), {"Authorization": "Bearer t"}, {}, ["t"]),
        (TokenAuth("t", prefix="SSWS"), {"Authorization": "SSWS t"}, {}, ["t"]),
        (
            TokenAuth("t", header="X-API-Key", prefix=None),
            {"X-API-Key": "t"},
            {},
            ["t"],
        ),
        (
            BasicAuth("alice", "pw d"),
            {"Authorization": "Basic " + base64.b64encode(b"alice:pw d").decode()},
            {},
            ["pw d"],
        ),
        (QueryApiKeyAuth("api_key", "k1"), {}, {"api_key": "k1"}, ["k1"]),
    ],
)
def test_auth_strategies(auth, headers, params, secrets):
    assert (auth.headers(), auth.params(), auth.secrets()) == (headers, params, secrets)


def test_token_provider_is_consulted_per_request_and_not_registered_as_secret():
    counter = iter(range(1, 10))
    auth = TokenAuth(token_provider=lambda: f"minted-{next(counter)}")
    assert auth.headers() == {"Authorization": "Bearer minted-1"}
    assert auth.headers() == {"Authorization": "Bearer minted-2"}
    assert auth.secrets() == []


@pytest.mark.parametrize(
    "build",
    [
        lambda: TokenAuth(),
        lambda: TokenAuth("tok", token_provider=lambda: "tok"),
        lambda: QueryApiKeyAuth("", "key"),
        lambda: QueryApiKeyAuth("param", ""),
    ],
)
def test_auth_rejects_invalid_construction(build):
    with pytest.raises(ValueError):
        build()


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            {
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "42",
                "X-RateLimit-Reset": "30",
            },
            RateLimitSnapshot(limit=100, remaining=42, reset=30.0),
        ),
        (
            {"x-rate-limit-limit": "600", "X-Rate-Limit-Remaining": "0"},
            RateLimitSnapshot(limit=600, remaining=0),
        ),
        (
            {"X-RateLimit-Limit": "soon", "X-RateLimit-Remaining": "3"},
            RateLimitSnapshot(remaining=3),
        ),
        ({"Content-Type": "application/json"}, None),
    ],
)
def test_parse_rate_limit_families(headers, expected):
    assert parse_rate_limit(headers) == expected


def test_retry_after_accepts_seconds_and_http_date():
    assert parse_rate_limit({"Retry-After": "7"}).retry_after_s == 7.0
    when = datetime.now(UTC) + timedelta(seconds=60)
    assert (
        55.0
        <= parse_rate_limit({"Retry-After": format_datetime(when)}).retry_after_s
        <= 61.0
    )


NOW = 1_750_000_000.0


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "3"}, 3.0),
        ({"Retry-After": "9999"}, 15.0),
        ({"Retry-After": "-5"}, 0.0),
        ({"X-Rate-Limit-Reset": str(int(NOW) + 8)}, 8.0),
        ({"X-Rate-Limit-Reset": str(int(NOW) - 100)}, 1.0),
        ({"X-Rate-Limit-Reset": str(int(NOW) + 9000)}, 15.0),
        ({"X-RateLimit-Reset": "5"}, 5.0),
        ({}, 1.0),
        ({"Retry-After": "not-a-date"}, 1.0),
    ],
)
def test_backoff_seconds_is_bounded(headers, expected):
    assert backoff_seconds(headers, cap=15.0, now=NOW) == expected


def test_capture_keeps_last_snapshot_across_empty_responses():
    capture = RateLimitCapture()
    assert capture.capture({"X-RateLimit-Remaining": "9"}) is not None
    assert capture.capture({"Content-Type": "text/html"}) is None
    assert capture.last.remaining == 9


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "eyJhbGciOiJIUzI1NiJ9",
        ),
        ("SSWS 00abcDEF123456", "00abcDEF123456"),
        (
            "postgresql://agent:"
            + "hunter2pass"
            + "@db:5432/kg",  # sanitizer:ignore - synthetic redaction fixture
            "hunter2pass",
        ),  # sanitizer:ignore - synthetic redaction fixture
        ("ghp_" + "a1B2" * 10, "a1B2a1B2"),
        ("AKIA" + "ABCDEFGHIJKLMNOP", "ABCDEFGHIJKLMNOP"),
        (
            'api_key="superSecretValue99"',  # sanitizer:ignore - synthetic redaction fixture
            "superSecretValue99",
        ),  # sanitizer:ignore - synthetic redaction fixture
    ],
)
def test_redact_text_hides_credential_shapes(text, secret):
    assert secret not in redact_text(text)


def test_redact_text_literals_and_passthrough():
    assert REDACTED in redact_text("v s3cr3t-v@lue!", secrets=["s3cr3t-v@lue!"])
    plain = "GET /api/stacks returned 200 with 14 items"
    assert redact_text(plain) == plain
    assert f"postgresql://agent:{REDACTED}@db:5432/kg" in redact_text(
        "postgresql://agent:"
        + "hunter2pass"
        + "@db:5432/kg"  # sanitizer:ignore - synthetic redaction fixture
    )


def _logger(name, redactor):
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record)

    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)
    log.handlers = [_Collector()]
    log.addFilter(redactor)
    log.propagate = False
    return log, records


def test_log_redactor_scrubs_args_literals_and_providers():
    redactor = LogRedactor(secrets=["one"])
    redactor.add_secret("two")
    redactor.add_secrets_provider(lambda: ["three"])
    log, records = _logger("sdk.test.redactor", redactor)
    log.info("auth Bearer %s", "abcdef123456token")
    log.info("one two three")
    assert "abcdef123456token" not in records[0].getMessage()
    assert records[1].getMessage().count(REDACTED) == 3


def test_log_redactor_provider_failure_never_breaks_logging():
    def broken():
        raise RuntimeError("boom")

    log, records = _logger("sdk.test.redactor2", LogRedactor(secrets_provider=broken))
    log.info("still logs")
    assert records[0].getMessage() == "still logs"


# --- neutral client protocol: response snapshot and the error taxonomy ---

from agent_connector_sdk.httpsupport.client_protocol import (  # noqa: E402
    AsyncHttpClient,
    HttpClient,
    HttpConnectError,
    HttpProtocolError,
    HttpResponse,
    HttpTimeoutError,
    HttpTooManyRedirectsError,
    HttpTransportError,
    map_transport_error,
    normalize_response,
)
from agent_connector_sdk.httpsupport.rate_limit import (  # noqa: E402
    DEFAULT_RETRY_AFTER_CAP_S,
)
from agent_connector_sdk.httpsupport.redaction import contains_secret  # noqa: E402


def test_normalize_response_copies_fields_and_defers_json():
    import httpx

    calls = []
    raw = httpx.Response(201, json={"ok": 1}, headers={"X-Id": "7"})
    original_json = raw.json

    def counting_json():
        calls.append(1)
        return original_json()

    raw.json = counting_json  # type: ignore[method-assign]
    snapshot = normalize_response(raw)
    assert isinstance(snapshot, HttpResponse)
    assert (snapshot.status_code, snapshot.headers["x-id"]) == (201, "7")
    assert snapshot.content == b'{"ok":1}' and calls == []
    assert snapshot.json() == {"ok": 1} and calls == [1]


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("ReadTimeout", HttpTimeoutError),
        ("ConnectError", HttpConnectError),
        ("TooManyRedirects", HttpTooManyRedirectsError),
        ("RemoteProtocolError", HttpProtocolError),
        ("SomethingElse", HttpTransportError),
    ],
)
def test_transport_errors_map_by_class_name(name, category):
    mapped = map_transport_error(type(name, (Exception,), {})("boom"))
    assert type(mapped) is category
    assert isinstance(mapped, HttpTransportError)
    assert str(mapped) == f"{name}: boom"


def test_client_protocols_are_structural():
    class Sync:
        def request(self, method, url, **kwargs):
            raise NotImplementedError

        def close(self):
            return None

    class Async:
        async def request(self, method, url, **kwargs):
            raise NotImplementedError

        async def aclose(self):
            return None

    assert isinstance(Sync(), HttpClient) and not isinstance(Sync(), AsyncHttpClient)
    assert isinstance(Async(), AsyncHttpClient)


def test_default_cap_bounds_backoff_and_secret_detection_is_membership_only():
    assert backoff_seconds({"Retry-After": "99999"}) == DEFAULT_RETRY_AFTER_CAP_S
    assert contains_secret("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.p.s")
    assert not contains_secret("GET /api/stacks returned 200")
    assert not contains_secret("")
