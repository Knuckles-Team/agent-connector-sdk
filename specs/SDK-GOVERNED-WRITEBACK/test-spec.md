# Test specification: governed write-back

| ID | Input/failure | Required assertion |
|---|---|---|
| WB-01 | Valid scoped change set and matching version | Dry-run exact diff/digest, no mutation. |
| WB-02 | Wrong tenant/connector, expired set, changed digest, extra field or stale version | Named refusal and zero transport apply calls. |
| WB-03 | Unapproved or proposal-only authorization | No source effect; approval must bind exact change-set/contract digests. |
| WB-04 | Audit reservation unavailable | Fail closed before source effect. |
| WB-05 | Same idempotency key and digest retried | Return prior durable effect; differing digest refuses. |
| WB-06 | Timeout after possible effect, then process restart | Durable uncertainty blocks retry; reconciliation `APPLIED` returns original receipt; `NO_EFFECT` permits one retry. |
| WB-07 | Simulate crash at each boundary | No duplicate effect, orphan approval, or false success; receipt stream is replayable. |
| WB-08 | Contributor-owned test app and graph service | Approval, apply, restart and reconciliation bind same tenant/connector/version and produce redacted durable receipts. |

Offline source PR gate includes focused pytest, Ruff, mypy, CCCC, Dupehound, KISS and wiring. WB-08 is acceptance-only until its optional environment exists; record **NOT RUN** explicitly on cloud PRs.
