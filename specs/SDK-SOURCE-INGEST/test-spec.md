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
