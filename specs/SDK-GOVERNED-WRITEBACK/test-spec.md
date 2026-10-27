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

Offline source PR gate includes focused pytest, Ruff, mypy, CCCC, Dupehound, KISS and wiring. WB-08 requires its contributor-owned environment; no execution evidence for that scenario is supplied by this definition change.


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


### Served immutable-intent acceptance

Start from an immutable durable change set produced by `GovernedWriteBack.dry_run`; its business fields and effect key define P.

1. POST /api/v1/ops/{op_id} with phase=prepare, params=P and null plan_ref, confirmation_ref and wallet_proof.
   Return frozen P, plan_ref, plan_digest, change-set ID/digest and effect key; assert zero provider effects.
2. POST the same operation with phase=confirm, unchanged P, returned plan_ref and the explicit authenticated human confirmation action.
   Persist the confirmation reference and unchanged P; assert zero effects and an unconsumed execution lease.
3. Sign the returned canonical SDK payload with a synthetic trusted key, after confirmation.
   Insert WalletProofRequest and confirmation metadata into the envelope without changing P.
4. POST the same operation with phase=`execute` and the completed envelope; require independent EG authorization and SDK verification.
   Assert the prepare, confirmation, SDK, plan validation, audit and reservation records contain the same plan_digest.
   Assert exactly one provider mutation and its durable receipt. Repeat the entire flow through MCP tools/call.
5. Change account, destination, amount, network, mode, operation or any nested business term after confirmation.
   Each change must yield PLAN_MISMATCH before dispatch, even if the attacker signs the changed intent with a trusted key.
   At the connector boundary, a binding mismatch yields scope_mismatch and zero effects.
6. Insert a valid proof into an unchanged confirmed P; assert neither recursive hashing nor PLAN_MISMATCH occurs.
   A changed signature, proof digest or confirmation association fails its separate validation without changing the computed intent digest.
7. Race two identical envelopes, restart and replay; read the same durable receipt without another effect.
   Missing envelope wiring, unavailable authority and uncertain completion refuse or reconcile without another submission.

These future served tests use the existing named acceptance cases. This definition change has not run these runtime scenarios.


## Repository source-effect acceptance

All tests below are proposed in `tests/test_repository_source_effect_served.py`; no runtime test or provider execution is added by this definition change. R004 retains its original generic acceptance in addition to every child case. Each case must exercise both the positive and negative assertions stated in requirements.md.

| Case | Requirement | Proposed test function | Required observation |
|---|---|---|---|
| WB-15 | SDK-GOVERNED-WRITEBACK-R004.1 | `test_generic_approval` | WB-15 permits one approved generic effect and refuses each invalid approval before transport apply. |
| WB-16 | SDK-GOVERNED-WRITEBACK-R004.2 | `test_generic_replay` | WB-16 observes one source effect for concurrent identical requests and restart replay. A conflicting replay causes zero additional effects. |
| WB-17 | SDK-GOVERNED-WRITEBACK-R004.3 | `test_audit_before_effect` | WB-17 records reservation-before-effect ordering and injects each reservation failure with zero provider mutations. |
| WB-18 | SDK-GOVERNED-WRITEBACK-R004.4 | `test_business_api` | WB-18 exercises an accepted API mutation and an API business-rule rejection, proving the rejected request never reaches a storage bypass. |
| WB-19 | SDK-GOVERNED-WRITEBACK-R004.5 | `test_request_binding` | WB-19 round-trips the complete request and seeded exact-byte vectors; changing each binding fails validation. |
| WB-20 | SDK-GOVERNED-WRITEBACK-R004.6 | `test_path_scope` | WB-20 serves an allowed nested path and every escape/scope variant, observing only the allowed path change. |
| WB-21 | SDK-GOVERNED-WRITEBACK-R004.7 | `test_approved_effect` | WB-21 approves one preview then changes each field independently; only the unchanged approved effect reaches the provider. |
| WB-22 | SDK-GOVERNED-WRITEBACK-R004.8 | `test_conditional_effect` | WB-22 races a competing commit after preflight. The approved write refuses without overwriting it. An unchanged base produces one revision. |
| WB-23 | SDK-GOVERNED-WRITEBACK-R004.9 | `test_effect_receipt` | WB-23 reads the durable attempt through a fresh ledger client. It matches the actual provider revision and complete receipt projection. |
| WB-24 | SDK-GOVERNED-WRITEBACK-R004.10 | `test_independent_readback` | WB-24 observes a separate provider read and matching bytes; corrupt, missing and unavailable reads never yield a successful receipt. |
| WB-25 | SDK-GOVERNED-WRITEBACK-R004.11 | `test_restart_reconcile` | WB-25 crashes before effect, after provider commit, after readback and after durable receipt. Restart resolves or remains uncertain without duplication. |
| WB-26 | SDK-GOVERNED-WRITEBACK-R004.12 | `test_served_journey` | WB-26 traces one real served effect and zero-effect negatives at the provider boundary. After restart it reads the identical durable result. |
| WB-27 | SDK-GOVERNED-WRITEBACK-R004.13 | `test_invalid_reservation_never_applies`, `test_file_reservation_refuses_a_different_change_set` | Missing IDs and mismatched file reservations refuse before the effect. |
| WB-29 | SDK-GOVERNED-WRITEBACK-R004.15 | `test_dry_run_rejects_mismatched_preview` | Mismatched source version, values, scope, changed fields and JSON types refuse without mutation. |
| WB-28 | SDK-GOVERNED-WRITEBACK-R004.14 | `test_uncertain_reconciliation_cannot_allow_retry` | An uncertain effect cannot permit a retry or trigger another apply. |


Use a contributor-owned disposable provider repository and an admitted production connector. Call its existing authenticated governed entrypoint with a real durable graph ledger. Record exact SDK, adapter and graph revisions, provider API/profile, registered operation ID and served route. Include canonical change-set and receipt digests plus redacted audit/attempt references. No production credentials or raw payload logs belong in evidence. A local fake and a helper call are useful unit fixtures but cannot satisfy WB-22 through WB-26 alone.

Use deterministic vectors: empty bytes, non-ASCII UTF-8, distinct CRLF/LF payloads and embedded zero bytes. Generate seeded bytes with `payload[index] = (73*index + 19) mod 256` for index=0..4095. Repeat the same immutable inputs across processes; assert identical canonical request/patch/receipt digests. The seeded case has exactly 4096 bytes. Different provider effect revisions legitimately produce different receipts; same-request durable replay must not. SHA-256 of empty bytes must equal `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Preserve all bytes and executable mode in independent revision readback.

The served journey previews without mutation, records approval of that exact digest and applies once. Independently read the actual returned revision and fetch the graph attempt using a separate client. Reconstruct the identical receipt after connector restart. Count actual provider mutation calls and durable effects. Submit concurrent identical requests and require one effect; inject a competing target update after preflight to require conditional refusal. Exercise missing/mismatched audit or approval and proposal-only authorization. Test wrong actor/tenant/connector/repository/target/path/base/payload/mode, unknown fields, changed contract pin and expired set. Include traversal/link/alias paths, provider business-rule denial and unsupported conditional mutation. Each refusal before mutation produces zero mutation calls. A readback failure after a possible mutation produces no false success or additional mutation; retain uncertainty until authoritative reconciliation.

Crash before provider mutation and after mutation before response. Also crash after independent readback before durable append, and after append before client response. Restart in a new process against the same ledger and provider. If no durable receipt exists, force provider causal lookup before any apply retry. Prove the original revision and receipt, or authoritative no-effect followed by at most one conditional effect. Otherwise require a typed unresolved result with zero reapply. Test an unrelated actor writing identical bytes, a moved target, unavailable provider history and a lost audit binding. None proves this request caused an effect.

Read-only ingestion and hydration must still work without any write capability. Attempting to use their output as approval refuses. Missing real transport composition or consumer wiring is evidence of an unexercised scenario, never an applied-success result. All new acceptance remains future implementation work until actual served evidence exists.
# Bound audit reservation proof

R004.3 checks reservation-before-effect ordering, missing and wrong bindings,
and durable reservation reuse on a proven-no-effect retry.
