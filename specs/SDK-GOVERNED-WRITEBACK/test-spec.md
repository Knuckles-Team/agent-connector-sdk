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


## Wallet proof acceptance

- WB-09: WB-09 validates the closed request and result models. Bind `SDK-GOVERNED-WRITEBACK-R001.1` in `tests/test_wallet_proof_served.py`.
- WB-10: WB-10 checks valid proofs, canonical payloads and independent authorization. Bind `SDK-GOVERNED-WRITEBACK-R001.2` in `tests/test_wallet_proof_served.py`.
- WB-11: WB-11 traces a served connector call through the verifier and governed apply. Bind `SDK-GOVERNED-WRITEBACK-R001.3` in `tests/test_wallet_proof_served.py`.
- WB-12: WB-12 proves zero effects for every refusal and unavailable dependency. Bind `SDK-GOVERNED-WRITEBACK-R001.4` in `tests/test_wallet_proof_served.py`.
- WB-13: WB-13 checks redaction, provenance and replay after restart. Bind `SDK-GOVERNED-WRITEBACK-R001.5` in `tests/test_wallet_proof_served.py`.
- WB-14: WB-14 requires served transport and durable read-back; direct verifier tests alone are insufficient. Bind `SDK-GOVERNED-WRITEBACK-R001.6` in `tests/test_wallet_proof_served.py`.

Use synthetic account bindings and keys. Positive served acceptance requires valid proof, explicit confirmation and independent EG authorization together.
Test each altered binding field, unknown scheme, duplicate JSON field, expired proof, future issuance, revoked key and unavailable trust authority.
Exercise two concurrent submissions and a process restart against the same durable effect key; read back the original receipt.
A proof-only request must never mutate the provider. Record exact revisions, served requests and redacted durable receipts.
These acceptance cases are planned; specification checks do not establish runtime delivery.
