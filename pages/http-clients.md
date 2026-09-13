# HTTP clients

A connector is an API client plus an MCP server. The SDK provides the governed
API-client layer: the HTTP client, TLS profiles, outbound authentication, RFC 9457
problem details, pagination helpers and progress reporting. The connector owns
only what is specific to its vendor: paths, payloads and models.

## A governed client and a tool that calls it

```python
from agent_connector_sdk.auth.static import bearer_auth
from agent_connector_sdk.config import setting
from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.pagination import ToolPage
from agent_connector_sdk.http.responses import arequest_json
from agent_connector_sdk.progress import ctx_progress
from agent_connector_sdk.tls.resolve import resolve_tls_profile


def build_client():
    """Composition root: references resolve here, once."""
    return create_async_http_client(
        HttpClientOptions(
            base_url=setting("DEMO_URL"),                       # https://api.example.com/v1
            auth=bearer_auth(setting("DEMO_TOKEN_REF")),        # openbao://apps/demo#TOKEN
            tls=resolve_tls_profile("demo"),                    # DEMO_TLS_PROFILE, DEMO_CA_BUNDLE_REF, ...
        )
    )


def register(mcp, client):
    @mcp.tool
    async def list_items(cursor: str | None = None, ctx=None) -> ToolPage:
        """List items, one page per call."""
        await ctx_progress(ctx, 0, 1, message="fetching items")
        document = await arequest_json(client, "GET", "/items", params={"cursor": cursor})
        await ctx_progress(ctx, 1, 1)
        return ToolPage.from_cursor(document["items"], document.get("next"))
```

The matching `mcp_source_presets.json` entry comes from
`preset_pagination("cursor", cursor_param="cursor")`, so extraction pages through
exactly what the tool returns.

## What every governed client does

| Behaviour | Detail |
|---|---|
| Timeouts | finite and positive; 30 seconds by default |
| Verification | always on, through a TLS profile or the platform trust store with TLS 1.2 or later |
| Plaintext | `http://` only to loopback, or with `allow_plaintext=True` and a logged warning |
| Proxies | never from the ambient environment; the TLS profile names one |
| Redirects | not followed |
| Retries | `RetryPolicy`: 3 attempts, exponential backoff with jitter, idempotent methods only; a connection never established is retried for any method; certificate failures are never retried |
| Rate limits | `Retry-After` (seconds or HTTP date) is honoured up to `max_retry_after`; beyond that, or for a non-idempotent request, the caller gets `HttpRateLimitedError.retry_after` |
| Bodies | `request_json`, `read_bounded` and `iter_bounded` bound the size (16 MiB by default) |
| Logging | one record per attempt on `agent_connector_sdk.http`: method, URL with credentials redacted, status or error class, attempt, elapsed time |
| Credentials | never in `headers` or `base_url`; always through `auth` |

## Errors

Every failure is an `HttpProblemError` (an `ApiError`) carrying an RFC 9457
`ProblemDetails`. A `application/problem+json` response is parsed; any other error
body is not copied, because it can echo request data.

| Error | When |
|---|---|
| `HttpUnauthorizedError` | 401 or 403; also an `UnauthorizedError` |
| `HttpRateLimitedError` | 429 |
| `UpstreamTimeoutError` | a timeout that is not retried |
| `UpstreamUnavailableError` | no connection |
| `TlsVerificationError` | the certificate did not verify |
| `RetriesExhaustedError` | every allowed attempt failed; `problem.extensions["attempts"]` |
| `ResponseTooLargeError` | a body exceeded its bound |

SDK-raised problems have types `urn:agent-connector-sdk:problem:<kind>`.

## TLS profiles

`resolve_tls_profile(service)` reads, in order: an explicit `profile` mapping; a
profile reference (`profile_ref`, `<SERVICE>_TLS_PROFILE_REF`, `TLS_PROFILE_REF`);
a named profile from `TLS_PROFILES_REF` or `TLS_PROFILES`; then
`<SERVICE>_CA_BUNDLE[_REF]`, `<SERVICE>_CA_DIRECTORY`, `<SERVICE>_CLIENT_CERT[_REF]`,
`<SERVICE>_CLIENT_KEY[_REF]`, `<SERVICE>_CLIENT_KEY_PASSWORD_REF`,
`<SERVICE>_PROXY_URL[_REF]`, `<SERVICE>_TLS_MINIMUM_VERSION`, each with a `TLS_*`
global fallback, and `SSL_CERT_FILE`/`SSL_CERT_DIR`.

- `verify` and `allow_insecure` are rejected. Verification cannot be turned off.
- `minimum_version` is `TLSv1.2` (default) or `TLSv1.3`.
- Material from a reference is written to mode-0600 files under
  `$XDG_RUNTIME_DIR/agent-connector-sdk/tls` and removed by `cleanup()` or at exit.
- A key or key password value is accepted only inside a document read from a
  secret reference; inline configuration must use `_ref` keys.

`ResolvedTLSProfile` adapts to `httpx_kwargs()`, `requests_kwargs()`,
`configure_requests_session()`, `psycopg_kwargs()` and `pymongo_kwargs()`.

## Outbound authentication

| Need | Use |
|---|---|
| Static bearer token | `bearer_auth("openbao://apps/demo#TOKEN")` |
| HTTP Basic | `basic_auth("user", "env://DEMO_PASSWORD")` |
| API key | `api_key_auth(ref, header="X-Api-Key")` or `query="apikey"` |
| OAuth 2.0 client credentials | `client_credentials_auth(ClientCredentialsConfig(...))`, or `ClientCredentialsTokenProvider` + `ClientCredentialsAuth` |
| On behalf of the MCP caller (RFC 8693) | `DelegatedTokenAuth(DelegationSettings.from_settings(), http_client=...)` |

Client-credentials tokens are cached, refreshed 30 seconds before expiry and
re-minted once on a 401; the client secret is resolved at every mint, so a
rotated secret is picked up. `ClientCredentialsConfig.from_settings()` reads
`OIDC_ISSUER` (or `OIDC_TOKEN_URL`), `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET_REF`,
`OIDC_AUDIENCE` and `OIDC_SCOPE`: the same service identity graph-os presents to
fleet MCP servers.

Delegation exchanges only the access token the connector's own MCP server
authentication verified; with no verified caller it raises `LoginRequiredError`.

### MCP endpoints

The same client-credentials implementation authenticates the connector-sync
runner and `connector-certify` to fleet MCP servers. A `TransportEndpoint` takes
`auth=client_credentials_auth(config)`; the runner's endpoint configuration takes:

```yaml
endpoint:
  url: https://demo-mcp.example.com/mcp
  client_credentials:
    issuer: https://idp.example.com/realms/fleet
    client_id: connector-sync
    client_secret_ref: openbao://apps/connector-sync#OIDC_CLIENT_SECRET
    audience: agent-services
```

## Conformance

`agent_connector_sdk.testing.http_clients.run_http_client_suite(factory)` checks a
connector's client factory against a local server: finite timeouts, `Retry-After`
retry, problem mapping, secret redaction and certificate verification.
`ScriptedHttpServer` and `issue_test_certificates()` are available for a
connector's own tests.
