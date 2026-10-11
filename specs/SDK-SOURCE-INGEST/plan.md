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
