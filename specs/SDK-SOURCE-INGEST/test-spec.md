# Test specification: source sync

| ID | Setup | Required assertion |
|---|---|---|
| SI-01 | Two pages from synthetic adapter, fake generated client | First `None` checkpoint then exact accepted checkpoint. Next page sees updated checkpoint only after receipt. |
| SI-02 | Timeout or ambiguous commit reply | Runner reads durable status and retries with same idempotency identity; no double advance. |
| SI-03 | Tenant/source/stream/manifest mismatch in receipt | Fail closed; no checkpoint advance or cross-tenant reuse. |
| SI-04 | Add optional field under declared compatible policy | Stable normalized digest/classification; accepted page proceeds. |
| SI-05 | Remove required field, change identifier type, add unknown enum, or change nested type | `REQUIRES_REVIEW` or `BREAKING` report. Page quarantined before sink. No checkpoint advance. |
| SI-06 | Approved candidate repair | Graph-owned candidate validation and shadow ingest precede activation; denial or failed shadow keeps old contract active. |
| SI-07 | Representative enterprise, document/feed and enrichment fixtures | Each adapter passes discovery, pagination, duplicate delivery, deletions, rate-limit and secret-redaction cases. |
| SI-08 | Restart after one accepted and one quarantined page against a contributor-owned graph | Accepted cursor resumes exactly once. Quarantined page remains replayable. Redacted receipts bind identities. |

Run offline focused pytest, Ruff, mypy, CCCC, Dupehound, KISS, and wiring checks on every source PR. SI-08 is an opt-in acceptance probe and may remain **NOT RUN** on cloud PRs without a graph endpoint. The source gate reports that state honestly.


## Paper-provider acceptance

The planned module is `tests/test_paper_source_served.py`; its cases bind R005.1 through R005.6.

| ID | Setup | Required assertion |
|---|---|---|
| SI-09 | Construct query, provider report, record and receipt models. | Unknown values, missing identities, invalid bounds and mismatched tenant refuse. |
| SI-10 | Two independent providers return the same DOI/revision and conflicting fields; a third fails. | One merged record preserves both sources and conflicts. Declared precedence ignores response order. Failure remains visible and result is partial. |
| SI-11 | Call registered connector search and download operations over MCP, then run the certified sync entry point. | The real caller reaches the shared contract, governed HTTP and generated SourceIngest with the pinned schema. |
| SI-12 | Exercise authentication, malformed input, provider failure, quotas, deadline, unsafe redirects, storage escape, media, size, integrity and parsing failures. | Each typed refusal reaches the caller. All-provider failure is failed. No unauthorized request, complete partial artifact or failed-stream checkpoint advance occurs. |
| SI-13 | Retry the same query and download; then change bytes for the same paper ID. | Identity and provenance remain deterministic. Same bytes reuse the artifact; changed bytes get a new digest. Credentials and private paths never appear. |
| SI-14 | Run `test_served_search_download_and_sync` with real MCP and controlled provider HTTP servers plus a running graph. | Observe original file bytes, merged fields and provider errors. Read back accepted graph records and checkpoints after restart. Failed providers remain retryable without duplicate healthy ingestion. |

Provider fixtures must include HTTP 429 with Retry-After and observed request timestamps.
Concurrent search and download calls must share the declared quota; no request may escape through another operation.
Test missing content metadata with a document containing a located title and author, then a malformed document.
Test truncated content, misleading HTML login responses, unsupported media, cross-host redirects and interrupted downloads.
Assert temporary files are removed and published documents match the recorded digest byte for byte.
Record exact revision, connector registration, commands, provider requests and redacted graph receipts for the served acceptance run.
Specification checks alone do not satisfy these runtime acceptance requirements.


## Platform fallback acceptance

The planned module is `tests/test_platform_fallback_served.py`; cases bind SDK-SOURCE-INGEST-R012.1 through R012.6.

| ID | Input | Required assertion |
|---|---|---|
| SI-15 | Separate read/search inventories; malformed request or policy. | Reject unknown fields, duplicate backends, incompatible authority, unbounded policy and wrong continuation binding. |
| SI-16 | First backend returns 503, next returns valid records; repeat with empty valid search. | Ordered bounded attempts select the second backend. Empty success stops the chain. Status distinguishes degraded and healthy results. |
| SI-17 | A real registered connector serves read/search/status through SDK tools/call. | The production dispatch_async calls the shared composition, governed HTTP and receiving MCP client. Trace their request identities. |
| SI-18 | All backends fail, none configured, unsupported operation, denied scope, 429, TLS failure or cancellation. | Return the exact typed terminal reason. Unsupported and unauthorized requests generate zero backend calls. No failed page advances a checkpoint. |
| SI-19 | Concurrent tenants, expired observations, signed URLs and secret-bearing upstream failures. | Status remains scoped and expires to unknown. Client results and logs retain safe provenance without credentials, raw queries or private URLs. |
| SI-20 | test_served_dispatch_fallback_and_status uses a real SDK server and two controlled local HTTP servers. | First fails and second succeeds; client sees ordered attempts, winning backend and subsequent status. All-failed and denied calls prove refusal through the same dispatcher. |

Start the SDK server with synthetic authenticated scopes, a certified connector registrar and fixed backend order.
Call its read/search tool over the MCP tools/call wire method. Helper calls or mocked dispatch_async cannot prove acceptance.
Local HTTP servers record request counts and monotonic timestamps. Inject two first-backend failures before the second returns valid data.
Assert the client receives two failed attempts followed by one success, the second backend ID and degraded channel status.
Call the registered status action and compare its backend, policy revision, observation time and tenant to the result.
Then make both backends fail. Assert chain_exhausted, null selected backend and no records; refuse an empty successful list.
Test no_backend separately from unsupported_capability, with no HTTP requests in either case.
Remove caller scope and assert unauthorized before dispatch; repeat with another tenant and assert no status or credential leakage.
Exercise HTTP 429, Retry-After, request deadline, cancellation and transport retries together; total observed calls never exceed the configured budget.
Test a valid empty search, malformed successful HTTP body, forbidden redirect, stale status and backend-specific continuation.
For the source path, pass a typed refusal through McpToolSourceAdapter.extract and assert no accepted RecordPage or checkpoint advance.
Record served requests, actual backend traces, schema/policy revisions and redacted client responses for each operation independently.
No live platform account is required. These cases remain NOT RUN until implementation and served integration acceptance exist.
