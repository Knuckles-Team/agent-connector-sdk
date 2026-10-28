# SDK-CENTRALIZED-CAPABILITIES — Design and implementation plan

Governing spec: [spec.md](spec.md).

## Existing system and reuse

The SDK already owns each capability below in an earlier row. This spec adds the `RateLimiter` class in `httpsupport/rate_limit.py`, the `next_url` pagination mode in `httpsupport/pagination.py`, and two extras, `vector` and `vector-chroma`. It indexes the capabilities and states the rule for connectors in one row each. Owner rows keep their contracts. Rows marked "this spec" had no earlier owner.

Search method: `grep -rn` over `specs/` for the module name and the capability term, then a read of each hit's row. The rows cited in the table are the result.

## Capability index

| Row | Capability | Owner row | Module or extra | Conformance |
|---|---|---|---|---|
| `SDK-CENTRALIZED-CAPABILITIES-R001` | Governed HTTP client and retry | `SDK-CONNECTOR-CONTROL-R780.3`, `SDK-CONNECTOR-CONTROL-R028` | `http/client.py`, `http/retry.py`, `http/transport.py` | pipelines `sdk-conformance` (`PIPE-GATES-R013`): direct `requests`, hand-built `httpx` clients, own retry loops. Warns; `--strict` blocks. |
| `SDK-CENTRALIZED-CAPABILITIES-R002` | Egress guard and pinned addresses | `SDK-CONNECTOR-CONTROL-R014.5`, `SDK-CONNECTOR-CONTROL-R014.16`, `SDK-CONNECTOR-CONTROL-R028.1`, `SDK-CONNECTOR-CONTROL-R033` | `http/egress.py`, `http/safe_post.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R003` | API client base and auth strategies | `SDK-CONNECTOR-CONTROL-R014.10`, `SDK-CONNECTOR-CONTROL-R028.3` | `http/support.py`, `httpsupport/auth.py`, `httpsupport/client_protocol.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R004` | Pagination helpers | `SDK-CENTRALIZED-CAPABILITIES-R004` | `http/pagination.py`, `httpsupport/pagination.py` (mode `next_url`) | Unit tests `tests/httpsupport/test_pagination_next_url.py`. No connector scan. |
| `SDK-CENTRALIZED-CAPABILITIES-R005` | Rate-limit telemetry and concurrency | `SDK-CENTRALIZED-CAPABILITIES-R005` | `httpsupport/rate_limit.py`, `mcp/concurrency.py` | Unit tests `tests/httpsupport/test_rate_limiter.py`. No connector scan. |
| `SDK-CENTRALIZED-CAPABILITIES-R006` | Error redaction and typed problems | `SDK-CONNECTOR-CONTROL-R780.2`, `SDK-CONNECTOR-CONTROL-R014.6`, `SDK-CONNECTOR-CONTROL-R014.12` | `exceptions.py`, `http/errors.py`, `http/problems.py`, `http/redaction.py`, `httpsupport/redaction.py`, `privacy_pii.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R007` | Payment challenge handling | `SDK-CONNECTOR-CONTROL-R049`, `SDK-FINANCE-SOURCES-R900` | `payments.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R008` | TLS profiles | `SDK-CONNECTOR-CONTROL-R017`, `SDK-CONNECTOR-CONTROL-R780.4` | `tls/resolve.py`, `tls/profile.py`, `tls/context.py` | pipelines `sdk-conformance` (`PIPE-GATES-R013`): verification off, silenced warning, hand-built SSL context. Warns; `--strict` blocks. The SDK static scan in the owner row stays. |
| `SDK-CENTRALIZED-CAPABILITIES-R009` | Credential and secret-reference resolution | `SDK-CONNECTOR-CONTROL-R014.4`, `SDK-CONNECTOR-CONTROL-R035`, `SDK-CONNECTOR-CONTROL-R900` | `credentials/references.py`, `credentials/resolver.py`, `credentials/openbao.py`, `credentials/provider.py` | pipelines `sdk-conformance` (`PIPE-GATES-R013`): hand-parsed `env://` and `openbao://` references. Warns; `--strict` blocks. |
| `SDK-CENTRALIZED-CAPABILITIES-R010` | Selected-provider credential profile | `SDK-CONNECTOR-CONTROL-R014.19`, `SDK-CONNECTOR-CONTROL-R027` | `credentials/provider_profile.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R011` | Token providers and source credentials | `SDK-CONNECTOR-CONTROL-R031`, `SDK-CONNECTOR-CONTROL-R900`, `SDK-CONNECTOR-CONTROL-R014.9` | `auth/tokens.py`, `auth/client_credentials.py`, `auth/static.py`, `credentials/source.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R012` | OIDC delegation and actor identity | `SDK-CONNECTOR-CONTROL-R014.8`, `SDK-CONNECTOR-CONTROL-R902`, `SDK-CONNECTOR-CONTROL-R780.1` | `auth/delegation.py`, `auth/oidc.py`, `identity.py`, `mcp/auth/` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R013` | Browser OAuth with PKCE | `SDK-CONNECTOR-CONTROL-R014.11`, `SDK-CONNECTOR-CONTROL-R046` | `auth/browser.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R014` | MCP server factory and served security | `SDK-CONNECTOR-CONTROL-R014.17`, `SDK-CONNECTOR-CONTROL-R014.18` | `mcp/server.py`, `mcp/served_security.py`, `mcp/middleware.py`, extra `mcp` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R015` | Tool surface and tool context | `SDK-CONNECTOR-CONTROL-R020`, `SDK-CONNECTOR-CONTROL-R026`, `SDK-CONNECTOR-CONTROL-R032`, `SDK-CONNECTOR-CONTROL-R050` | `mcp/tool_surface.py`, `mcp/method_tools.py`, `mcp/context.py`, `mcp/action_dispatch.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R016` | GraphQL | `SDK-CONNECTOR-CONTROL-R014.12`, `SDK-CONNECTOR-CONTROL-R030`, `SDK-CONNECTOR-CONTROL-R043`, `SDK-SOURCE-INGEST-R901` | `mcp/graphql.py`, `source_connectors/connectors/graphql_document.py`, extra `graphql` | pipelines `sdk-conformance` (`PIPE-GATES-R013`): own GraphQL client. Pipelines `connector-graphql` (`PIPE-GATES-R012`): the extra declaration. Both warn; `--strict` blocks. |
| `SDK-CENTRALIZED-CAPABILITIES-R017` | A2A protocol | `SDK-CONNECTOR-CONTROL-R014.21`, `SDK-CONNECTOR-CONTROL-R041` | `a2a/models.py`, `a2a/client.py`, `a2a/app.py`, extra `a2a` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R018` | Engine client adapter and compute | `SDK-CONNECTOR-CONTROL-R014.23`, `SDK-CONNECTOR-CONTROL-R014.24`, `SDK-CONNECTOR-CONTROL-R005` | `sinks/epistemic_graph.py`, `compute/engine.py`, `decide/` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R019` | Ingest bindings and source adapters | `SDK-SOURCE-INGEST-R001`, `SDK-SOURCE-INGEST-R005`, `SDK-SOURCE-INGEST-R017` | `ingest/`, `adapters/`, `runner/syncing.py`, `ports/source_adapter.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R020` | Database sources | `SDK-SOURCE-INGEST-R900`, `SDK-SOURCE-INGEST-R004`, `SDK-CONNECTOR-CONTROL-R901` | `source_connectors/universal.py`, `identifiers.py`, extras `db`, `mssql` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R021` | Feed and document sources | `SDK-SOURCE-INGEST-R800`, `SDK-SOURCE-INGEST-R005` | `source_connectors/connectors/rss.py`, `arxiv.py`, `web.py`, `rest.py`, extra `feeds` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R022` | Message streams | `SDK-CONNECTOR-CONTROL-R782`, `SDK-FINANCE-SOURCES-R900.1` | `streaming.py`, `adapters/event_feed.py`, extra `stream` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R023` | Market data | `SDK-FINANCE-SOURCES-R001`, `SDK-FINANCE-SOURCES-R900` | `finance/market_data.py`, `finance/`, extra `market` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R024` | Data preparation | `SDK-SOURCE-INGEST-R803` | `data_prep/`, extra `dataprep` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R025` | Embedding client | `SDK-CONNECTOR-CONTROL-R014.22` | `embeddings.py`, extras `vector`, `vector-chroma` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R026` | Vendor extractors | `SDK-SOURCE-INGEST-R006` | `vendor_extractors/` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R027` | Ontology and content packs | `SDK-CONNECTOR-CONTROL-R067`, `SDK-CONNECTOR-CONTROL-R021`, `SDK-CONNECTOR-CONTROL-R022`, `SDK-CONNECTOR-CONTROL-R019` | `ontology/`, `artifacts/pack.py`, `artifacts/ontology_imports.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R028` | Connector manifest and integrity | `SDK-CONNECTOR-CONTROL-R015`, `SDK-CONNECTOR-CONTROL-R015.1`, `SDK-CONNECTOR-CONTROL-R650`, `SDK-CONNECTOR-CONTROL-R045.11` | `manifest/`, extra `integrity` | SDK duplicate-definition scan in the owner row (`testing/duplicate_symbol_scan.py`). No pipelines gate runs it. |
| `SDK-CENTRALIZED-CAPABILITIES-R029` | Certification and fingerprints | `SDK-CONNECTOR-CONTROL-R003`, `SDK-CONNECTOR-CONTROL-R007`, `SDK-CONNECTOR-CONTROL-R015`, `SDK-CONNECTOR-CONTROL-R045.11` | `certify/`, script `connector-certify` | `connector-certify` check run by the connector. Pipelines gate runs none. |
| `SDK-CENTRALIZED-CAPABILITIES-R030` | Connector identity | `SDK-CONNECTOR-CONTROL-R071` | `connector_identity.py` | Owner-row check `ConnectorIdentityError`. Pipelines name gate named in the owner row. |
| `SDK-CENTRALIZED-CAPABILITIES-R031` | Governed write-back | `SDK-GOVERNED-WRITEBACK-R002`, `SDK-GOVERNED-WRITEBACK-R003` | `writeback/`, `writeback_sinks/` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R032` | Runner and CLI bootstrap | `SDK-CONNECTOR-CONTROL-R014.14`, `SDK-SOURCE-INGEST-R805` | `runner/`, `mcp/env_drift.py`, script `connector-sync` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R033` | Health and observability | `SDK-CONNECTOR-CONTROL-R065`, `SDK-CONNECTOR-CONTROL-R050` | `runner/health_state.py`, `runner/health_server.py`, `runner/logs.py`, `progress.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R034` | Configuration, paths, and locks | `SDK-CONNECTOR-CONTROL-R016`, `SDK-CONNECTOR-CONTROL-R029`, `SDK-CONNECTOR-CONTROL-R014.7`, `SDK-CONNECTOR-CONTROL-R014.2`, `SDK-CONNECTOR-CONTROL-R034`, `SDK-CONNECTOR-CONTROL-R780.5` | `config.py`, `utilities.py`, `paths.py`, `file_lock.py`, `library_state.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R035` | Privacy, entitlements, and external access | `SDK-CONNECTOR-CONTROL-R014.6`, `SDK-CONNECTOR-CONTROL-R014.13`, `SDK-CONNECTOR-CONTROL-R014.15`, `SDK-CONNECTOR-CONTROL-R025`, `SDK-CONNECTOR-CONTROL-R036` | `privacy*.py`, `entitlements.py`, `contracts.py`, `access_contract.py` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R036` | Repository transport and planned source client | `SDK-SCM-R001`, `SDK-REPOSITORY-TRANSPORT-R001` | `repository/` (source client pending) | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R037` | Plugin entry-point groups | `SDK-CONNECTOR-CONTROL-R014.20` | `pyproject.toml` entry-point groups | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R038` | Connector test kit | `SDK-CONNECTOR-CONTROL-R004`, `SDK-CONNECTOR-CONTROL-R014.1` | `testing/` | SDK import scan `scan_many_packages`. No pipelines gate runs it. |
| `SDK-CENTRALIZED-CAPABILITIES-R039` | Domain record models | `SDK-SOURCE-INGEST-R009`, `SDK-SOURCE-INGEST-R804`, this spec | `taxonomy/`, `earth_observations/`, `voice_supply_chain/` | unchecked |
| `SDK-CENTRALIZED-CAPABILITIES-R040` | Optional dependencies come from SDK extras | `SDK-CENTRALIZED-CAPABILITIES-R040` | `pyproject.toml` `[project.optional-dependencies]` | pipelines `sdk-conformance` (`PIPE-GATES-R013`): a direct pin of a package an SDK extra carries. Warns; `--strict` blocks. SDK test `test_every_extra_has_a_row`. |

## Architecture

A connector depends on the SDK only. The SDK modules sit between the connector and the engine, the secret store, and the network. A connector that ships its own copy of a capability splits the policy. The SDK then enforces its egress, redaction, and retry rules on only part of the fleet.

## Interfaces and data model

Each module's interface stays in its owner row. This spec adds three interfaces.

`PaginationIterator(fetch_page, endpoint, *, mode="next_url", next_path="next", base_url=None, items_path=..., max_pages=100, ...)` and its async twin `AsyncPaginationIterator` in `agent_connector_sdk.httpsupport.pagination`. The mode reads the next URL at `next_path` in the body. It resolves the URL against the current request URL with `urljoin`. `base_url` makes a relative `endpoint` absolute, and the mode refuses a relative endpoint without it. The first request fixes the origin. A next URL with another scheme, host, or port raises `PaginationOriginError`, a subclass of `HttpProblemError` with the problem kind `cross-origin-next-url`. A URL that the sweep already fetched ends the sweep with `truncated` set.

`RateLimiter(min_interval_seconds, *, clock=time.monotonic, sleep=asyncio.sleep)` in `agent_connector_sdk.httpsupport.rate_limit`, exported from `agent_connector_sdk.httpsupport`. The coroutine `wait()` sleeps only as long as the minimum interval needs. Concurrent callers queue on one lock. The first call never waits. The class is also an async context manager. The property `min_interval_seconds` returns the clamped interval.

The `vector` extra carries the vector-store clients `qdrant-client`, `psycopg[binary,pool]`, and `pymongo`. The `vector-chroma` extra carries the embedded-index store client `chromadb` and its index adapter `llama-index-vector-stores-chroma`. The `psycopg` and `pymongo` floors equal the `db` floors. `test_vector_extras_share_db_floors` checks this.

## Live integration path

The connector entry point calls the server factory, the runner, and the governed client. Each owner row names its own call site. The index test in `test-spec.md` checks that each module path and owner row exists.

## Conformance state

The pipelines gate `sdk-conformance` (`PIPE-GATES-R013`) scans a connector for an SDK capability it reimplements. It checks rows R001, R008, R009, R016, and R040, and each finding cites its row. It warns by default and blocks under `--strict`. A connector turns strict on once it is migrated. The warn-mode findings across the fleet are the migration backlog. The SDK unit tests also check `R004`, `R005`, and `R040` inside the SDK. The other rows have no automated check. The SDK also ships three scans: `testing/fleet_migration.py`, `testing/duplicate_symbol_scan.py`, and the TLS scan in `SDK-CONNECTOR-CONTROL-R017`. Each connector or a test run must call them.

## Quality and release gates

Run `pipelines-hook spec-standard`, `pipelines-hook spec-status`, and `ste-staged` on the spec directory. The index test needs no network.

## Risks, alternatives, and decisions

Decision: one index spec with one row per capability, not one spec per capability. A second spec for an owned capability is a defect under the spec standard. Decision: the SDK declares the vector-store clients as two extras, `vector` and `vector-chroma`. The vector connector selects one store per deployment. The `qdrant-client`, `psycopg`, and `pymongo` clients are small, so they share the `vector` extra. The embedded-index store client and its index adapter pull a large native stack and the index framework. They install apart, as `mssql` installs apart from `db`. One extra per store adds names without benefit, because three of the four stores are small. The `vector` extra lists `psycopg` and `pymongo` with the `db` floors and does not depend on `db`. The `db` extra also pulls the MySQL and Oracle drivers, which a vector store does not need.

Decision: the next-URL mode extends the existing iterator, not a new helper. Its origin rule matches `next_link_cursor` in `http/pagination.py` and reuses the same origin key. Default ports compare equal to explicit ones.

Decision: the shared `RateLimiter` lives in `httpsupport/rate_limit.py`, next to the rate-limit telemetry. Two connectors carried identical copies. The SDK keeps their constructor argument and `wait()` coroutine, so their switch is an import change. The connectors' `build_async_client` wrappers stay in the connectors. Each one builds `create_async_http_client` options from the connector's own user agent and endpoint type.

Risk: the index drifts from the modules. The index test closes this risk once it lands.

## Amendment 2026-10-27: credential-bearing URLs

The first and followed URLs must have an HTTP(S) origin without userinfo.
Malformed origins and URLs with userinfo raise `PaginationOriginError` before
fetching. Explicit port zero remains distinct from the default port. The
problem detail is static and does not echo any URL.

## Amendment 2026-10-27: bind Link pagination

Link mode requires an absolute endpoint or `base_url`, so it can bind the
first origin before making a request. Resolve each next link against the
current URL. Apply the same origin, userinfo and loop guards as `next_url`.
# Amendment: token endpoint redirects

For SDK-CENTRALIZED-CAPABILITIES-R011, token requests must not follow redirects.
Reject a redirect response even when it contains a token. This prevents a
redirect target from receiving credentials or a delegated subject token.

## Linear Link parsing (R004.3)

Scan Link targets and next relations once in header order. Preserve the prior
first-match grammar. The existing origin guard still admits every followed URL.

## Partial-page cursor safety (R004.5)

When the item budget cuts a page, its provider cursor points past unseen
records. Return no cursor for that partial page. Keep `truncated` true. A cap
on a full page can return the provider cursor. Exact mid-page resume remains
open work.
