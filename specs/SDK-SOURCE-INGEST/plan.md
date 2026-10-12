# Implementation design: source sync

1. Define normalized stream/manifest identity and checkpoint invariants in existing manifest and runner types. Keep generated `SourceCheckpoint` as the sole cursor type.
2. Add deterministic drift classification before the sink call and a typed quarantine report. Separate pure classification from I/O so adversarial fixtures run offline.
3. Route every accepted page and deletion reconciliation through generated SourceIngest operations with idempotent retries. Treat uncertain replies as a checkpoint read, not an automatic advance.
4. Port representative enterprise, document/session/feed, and vendor enrichment adapters in small slices using existing SDK ports and presets. Preserve provider license, paging, and rate limits in vendor adapters.
5. Add candidate-repair handoff as a proposal only. Activate only after graph-owned validation, shadow ingest, explicit approval, and restart proof.

Each change carries focused unit/contract tests. A final opt-in integration job runs against a provisioned graph instance and reports exact receipts.

## Ingest worker (SDK-SOURCE-INGEST-R010, R011)

The worker is a thin loop: ask the engine for admission, lane floors and routing, claim, execute with the existing source-effect runners, ack, commit. It owns no scheduling policy, so a change of lane or priority is an engine change only. The command refuses to start when the engine lacks the task-queue methods.


## Paper-provider sources (SDK-SOURCE-INGEST-R005)

Data flow: authenticated connector `tools/call` -> shared paper contract -> provider adapters -> governed HTTP -> normalized results or document receipt.
Ingestion flow: `connector-sync --once` -> certified MCP session -> provider stream -> generated SourceIngest -> accepted checkpoint.

Existing code: `McpToolSourceAdapter.discover` at `agent_connector_sdk/adapters/mcp_tool.py:107` verifies the live schema pin.
Its `extract` at line 118 calls the connector tool and maps records into generated source types.
`ConnectorWorker._sync` at `agent_connector_sdk/runner/worker.py:180` calls the existing sync lifecycle.
The command entry point is `agent_connector_sdk/runner/cli.py:153`.
`fetch_page` at `agent_connector_sdk/adapters/web_fetch.py:86` fetches HTML through governed HTTP and extracts page metadata.
`WebFetchSourceAdapter.extract` at line 182 supplies checkpointed URL pages.
`create_async_http_client` at `agent_connector_sdk/http/client.py:97` supplies transport and TLS policy.

Reachable today: no. The MCP and web-fetch paths are reachable, but no shared paper-provider contract is present.
The web-fetch helper returns normalized HTML or `None`; it does not supply complete binary downloads or typed provider failures.
Reuse HTTP construction, source types, schema certification and sync paging. Do not route paper downloads through HTML text normalization.
Add the shared provider contract and bounded document transfer to the existing adapter package.
Each connector supplies provider-specific search, cursor handling and document offers, then registers the served operations with the SDK.
No paper-serving connector registration is established by this specification; that caller wiring remains required for acceptance.

The `exact_identity` rule groups matching normalized DOI and revision pairs, or explicit canonical aliases supplied by a provider.
Normalize a DOI by removing its URI prefix and case-folding. Preserve the original identifier as provenance.
Otherwise use the provider and its stable record ID; never merge on a similar title alone.
Different known revisions remain distinct. An unknown revision does not establish equality with a known revision.
Sort merged results by canonical identity for replayable output; ranking and semantic equivalence remain outside the SDK.
The `declared_precedence` rule selects nonempty fields by configured provider order, independent of response arrival.
Retain alternate conflicting values and their sources. A missing field remains null unless a document parser extracts it.
The `content_fallback` rule uses deterministic local parsing only for missing fields.
Store parser identity, document digest and page or section location with each extracted value.
A parse failure remains visible and never fabricates metadata or erases a valid provider value.

The `bounded_provider_query` defaults are eight providers, 100 records per provider page and a 60-second request deadline.
An authorized configuration may lower or replace these limits. Continuation binds query digest, provider set and schema version.
A successful provider can return zero records; a failed provider must return a failure report.
At least one successful provider plus a failure yields `partial`; no successful provider yields `failed`.
Use separate provider streams for ingestion so healthy accepted pages do not advance a failed provider's cursor.
Partial search results are never authoritative deletion snapshots. Preserve the existing generated SourceCheckpoint authority in EG.

The `provider_quota` rule requires declared request and concurrency limits before any provider call.
Search, retries and downloads share the provider's credential-scoped quota gate.
Honor provider Retry-After delays; never retry earlier than both the declared quota and provider delay permit.
Default to two read retries within the request deadline. If a delay exceeds that deadline, report `rate_limited` with retry timing.
Quota allocation must cover all concurrent callers sharing those credentials; unavailable shared quota enforcement refuses the provider call.
The SDK enforces supplied limits; it does not choose routing, admission policy or a retry schedule beyond those bounds.

The `complete_document` default caps a document at 50 MiB, with a 30-second transfer deadline.
Stream bounded chunks to a temporary file inside the authorized tenant storage root; do not buffer the entire body.
Recheck destination policy for redirects and refuse traversal, symlink escape or credentials sent to an unapproved host.
Require declared PDF or HTML media, valid content structure and a complete transfer; reject login pages and truncated bodies.
Compare advertised length and checksum when present, compute SHA-256, then atomically install the file under a digest-derived name.
A server without Content-Length is valid only after clean transfer completion and format validation within the byte cap.
Retain the complete original document bytes; metadata extraction must not replace them.
Repeated identical bytes reuse the same tenant-scoped artifact after digest verification.
Changed bytes produce a different receipt and never overwrite an existing digest artifact.
Failure or cancellation removes temporary files and returns a typed reason without a complete artifact reference.
Local artifact storage is authorized source material, not a graph cursor or semantic authority.

Decision: extend R005 and reuse certified MCP source ingestion for provider streams.
Rejected alternative: a separate scholarly search runtime with its own graph store, checkpoint authority and ungoverned downloader.
Cross-repository rows: SDK-SOURCE-INGEST-R001 owns receipt-bound checkpoints; SDK-CONNECTOR-CONTROL-R021 owns declared source access contracts.
Connector packages own provider API bindings. EG's SourceIngest contract owns durable acceptance and graph interpretation.
GraphOS supplies authenticated hosting and operator-approved limits. AU consumes results without selecting providers or creating approval policy.
References: no research-paper derivation is claimed for this contract.


## Platform backend fallback (SDK-SOURCE-INGEST-R012)

Data flow: authenticated connector tools/call -> registered handler -> dispatch_async -> shared fallback client -> governed backend HTTP -> typed result.
SDK selects equivalent adapters mechanically under connector policy; it never chooses the user's goal, semantic query or admission policy.
GraphOS authentication and authorization remain prerequisites. Connector packages own platform APIs and credential references; EG owns decisions and durable records.
R005.1 through R005.6 aggregate independent paper providers. R012 stops at one valid equivalent backend and does not aggregate their results.

The new closed `PlatformCapability` fields are platform_id, channel_id, operation, schema_revision, policy_revision, required_scope and backends.
Operation is `read` or `search`; separate entries are mandatory when one backend supports only one operation.
Each BackendPolicy contains backend_id, certified adapter identity/version, `enabled`, auth_mode, credential_ref, allowed_destinations, equivalence_contract and quota_group.
Auth_mode is public or credential; only declared public access permits a null credential_ref. Caller scope remains mandatory.
It also contains max_attempts, timeout_ms, retry_policy and output_schema_digest; list order is authoritative.
Equivalence binds the same platform, resource visibility, account scope, query semantics and output contract.
A backend offering only public data cannot replace an authenticated private read or silently narrow its coverage.
Installed software or a reachable port alone does not establish an available capability.

PlatformRequest carries request_id, authenticated tenant/principal/connector binding, platform_id, channel_id, operation, target, query, continuation, limit and deadline.
Exactly target for read or query for search is required. Reject unknown fields and invalid or excessive limits before any backend dispatch.
Continuation, when present, binds tenant, query digest, backend, policy revision and output schema; it cannot migrate to a different backend.
Pin each request's policy snapshot. A concurrent policy update applies to the next request and never changes an in-flight chain.
PlatformResult contains request_id, request_digest, outcome, reason, records, continuation, selected_backend, attempts, skipped_backends, channel_status and provenance.
Outcome is `ok` or `refused`; a refusal has a required reason, no records and no successful continuation.
Attempt fields are sequence, backend_id, attempt_number, outcome, reason, started_at, elapsed_ms, retry_after_ms and response_digest.
Transient reasons are `connection_failed`, `timeout` and `upstream_unavailable`.
Terminal reasons are `rate_limited`, `unauthorized`, `egress_denied`, `trust_failed`, `invalid_response`, `not_found` and `cancelled`.
Success has a null reason. HTTP status is optional numeric evidence; omit raw error bodies.
An attempt outcome is `ok`, `failed` or `cancelled`; record one entry per actual outbound attempt, including lower-level retries.
Skipped backend configuration is reported separately with a reason; it must never appear as an attempted network call.
Selected_backend is the successful backend, or null on refusal. No cached success may be presented as the current request's backend.

The `ordered_equivalent_fallback` rule starts with the first eligible backend and preserves list order.
Eligibility requires declared capability, active configuration, certification, the declared authentication mode, matching authority and an approved destination.
An empty eligible list returns no_backend; an unknown platform or operation returns unsupported_capability without network activity.
Request-level authorization failure returns unauthorized before selecting any backend.
Missing backend configuration is visible, but missing or denied caller authority cannot be bypassed by selecting another backend.
Default bounds are four backends, two attempts per backend, eight total attempts, ten seconds per attempt and thirty seconds overall.
Default result bounds are 100 records and one MiB of response bytes; an admitted configuration may lower these ceilings.
Validate every configured bound. The outer remaining deadline limits connect, transfer, parsing, quota waiting, backoff and all retries.
Use the existing RetryPolicy for idempotent reads; pass its actual attempts into the outer budget rather than nesting hidden retries.
Only transport connection failures, timeouts and HTTP 408 or 5xx permit the next declared equivalent backend.
HTTP 429 honors Retry-After within the remaining budget; exhausted waiting returns rate_limited and does not switch credentials or quota groups.
HTTP 401/403, egress denial, certificate failure, malformed output and authoritative not-found stop the chain with the matching typed refusal.
An empty, valid search response is success. Empty required read content is invalid_response, not a synthetic successful document.
If all attempted eligible backends fail transiently, return chain_exhausted with their complete ordered history.
Deadline expiry returns deadline_exceeded; cancellation stops outstanding work and forbids subsequent backend attempts.
No fallback crosses into write operations, login automation, browser interaction or native device effects.

ChannelStatus contains platform_id, channel_id, operation, policy_revision, selected_backend, health, backend_states, observed_at and expires_at.
Health is unknown before observation, healthy for first-choice success, degraded for fallback success, and unavailable for observed total failure.
Each backend state distinguishes untested, disabled, unconfigured, healthy and failed, with its latest safe reason and observation time.
Caller refusals do not change backend health; only authorized observations do.
Status snapshots are scoped by tenant, connector, account authority and capability; they never authorize a later request.
The default status lifetime is sixty seconds. Expired observations become unknown and expose the previous timestamp without claiming current health.
The registered status action returns these observations without probing or changing configuration; active probes require a separately admitted read.
Status must derive from actual calls or declared probes. Preserve unsupported entries rather than implying uniform platform support.
Read results retain source identity, backend, retrieval time, content digest and declared coverage alongside each returned record.
An identical read retry retains request identity but may observe changed content. It guarantees neither durable effects nor unchanged content.
Existing SourceIngest owns accepted records and checkpoints. A refused read must not be mapped to an empty accepted page or deletion snapshot.

Production call sites: register_tool_surface at mcp/tool_surface.py:121 installs connector registrars; it does not itself implement fallback.
`dispatch_async` at `agent_connector_sdk/mcp/action_dispatch.py:194` invokes the resolved method through `invoke_client_method`. It currently returns that method's result.
McpToolSourceAdapter.extract at adapters/mcp_tool.py:118 receives session.call_tool results at line 131 before record mapping.
Its pinned tool schema and raw-record mapping must preserve successful records and reject a PlatformResult refusal before page construction.
ConnectorWorker._sync at runner/worker.py:180 remains the ingestion caller; no new runner or checkpoint store is needed.
`fetch_page` at `agent_connector_sdk/adapters/web_fetch.py:86` is a governed read backend. It collapses HTTP and empty-content failures to None.
Extend that adapter boundary with typed outcomes rather than guessing a reason from None or duplicating its HTTP implementation.
Reuse `create_async_http_client` at `agent_connector_sdk/http/client.py:97` for HTTP. Compose `RetryPolicy` at `agent_connector_sdk/http/retry.py:71` for retries.
Add shared platform models and fallback composition under `agent_connector_sdk/adapters`. Register connector-owned read/search/status methods through existing registrars.
The authenticated MCP client receives PlatformResult; the source adapter consumes it only after success and schema validation.
Reachable today: generic dispatch and one web reader exist. Platform inventory, equivalent-backend fallback, status composition and refusal mapping are missing.
All R012 rows require actual connector registration and served acceptance.

Decision: reuse the SDK dispatcher, governed HTTP, certification and SourceAdapter boundary.
Rejected alternative: a separate routing service that selects semantic actions or introduces another health authority and ingestion store.
Operational status is bounded observation; it is neither EG knowledge nor an authorization decision.
References: the source motivates ordered per-channel backends and observed status; no arXiv derivation is claimed.
