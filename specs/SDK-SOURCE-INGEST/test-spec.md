# Test specification: source sync

| ID | Setup | Required assertion |
|---|---|---|
| SI-01 | Two pages from synthetic adapter, fake generated client | First `None` checkpoint then exact accepted checkpoint; next page sees updated checkpoint only after receipt. |
| SI-02 | Timeout or ambiguous commit reply | Runner reads durable status and retries with same idempotency identity; no double advance. |
| SI-03 | Tenant/source/stream/manifest mismatch in receipt | Fail closed; no checkpoint advance or cross-tenant reuse. |
| SI-04 | Add optional field under declared compatible policy | Stable normalized digest/classification; accepted page proceeds. |
| SI-05 | Remove required field, change identifier type, add unknown enum, or change nested type | `REQUIRES_REVIEW` or `BREAKING` report; page quarantined before sink; no checkpoint advance. |
| SI-06 | Approved candidate repair | Graph-owned candidate validation and shadow ingest precede activation; denial or failed shadow keeps old contract active. |
| SI-07 | Representative enterprise, document/feed and enrichment fixtures | Each adapter passes discovery, pagination, duplicate delivery, deletions, rate-limit and secret-redaction cases. |
| SI-08 | Restart after one accepted and one quarantined page against a contributor-owned graph | Accepted cursor resumes exactly once; quarantined page remains replayable; redacted receipts bind identities. |

Run offline focused pytest, Ruff, mypy, CCCC, Dupehound, KISS, and wiring checks on every source PR. SI-08 is an opt-in acceptance probe and may remain **NOT RUN** on cloud PRs without a graph endpoint. The source gate reports that state honestly.
