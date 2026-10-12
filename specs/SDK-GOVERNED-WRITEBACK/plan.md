# Implementation design: governed write-back

1. Preserve generated graph types and the current `WriteBackPort`, `GovernedWriteBack`, `DurableWritableConnector`, transport and `WriteBackLedger` composition.
2. Bind audit reservation and deterministic approval to the exact canonical digest and source version before mutation. Keep proposal evaluation separate.
3. Add a synthetic writable adapter with explicit prior-effect and reconciliation semantics; then migrate one real vendor adapter using its business API.
4. Exercise crash boundaries before source effect, after effect before receipt, and after receipt before response. Restart must recover from graph-owned receipts.
5. Publish redacted approval, attempt and reconciliation evidence only after the cross-process probe passes; then widen adapter support in small slices.


## Wallet signature verification (SDK-GOVERNED-WRITEBACK-R001)

Data flow: GraphOS confirmed plan -> authenticated connector operation -> SDK verifier -> existing authorization/audit -> source effect -> durable receipt.
Existing code: `GovernedWriteBack.apply` (`agent_connector_sdk/writeback/service.py:74`) resolves authorization and reserves audit before transport apply.
`DurableWritableConnector.apply` (`agent_connector_sdk/writeback/connector.py:75`) reads durable prior effects; its reconciliation path handles uncertainty.
Reachable today: no wallet verification path exists. The ordinary governed apply composition is reachable.
Add one shared verifier and a typed proof input to that composition; do not duplicate authorization or replay storage.
Expose the verifier through the admitted connector's authenticated operation so GraphOS imports one SDK contract, not cryptographic code.
Bind the returned fact to that caller and request; an untrusted JSON result cannot grant permission.

The initial explicit profile is `ed25519_jcs`, for wallets with a trusted Ed25519 key binding.
Its signed message is UTF-8 `SDK-WALLET-INTENT`, one zero byte, UTF-8 `1`, one zero byte, then RFC 8785 canonical JSON.
The JSON contains every WalletProofRequest field except signature; identities and digests come from authenticated or durable authority.
The exact signed keys are `tenant_id`, `actor_id`, `connector_id`, `operation_id`, `account_id`, `wallet_id`, `network_id`, `key_id`,
`plan_digest`, `change_set_digest`, `idempotency_key`, `scheme`, `nonce`, `issued_at` and `expires_at`.
All values are nonempty strings except the two timestamps, which are integer UTC seconds within the exact JSON integer range.
The detached `signature` is unpadded base64url encoding of exactly 64 bytes; the trusted Ed25519 key is exactly 32 bytes.
The fixed domain/version prefix is outside the canonical JSON. Do not normalize strings or accept alternate field aliases.
Nonce equals the immutable change-set ID. Include scheme, wallet and network to prevent reuse across protocols and networks.
Reject extra or duplicate fields, invalid Unicode and nonfinite numbers. Amounts remain exact decimal strings inside the bound change-set digest.
Use Ed25519 verification from a maintained cryptographic library with RFC 8032 test vectors; no handwritten cryptographic primitive.
Other signature schemes require an explicitly specified serialization, verifier and network binding; unsupported profiles refuse without fallback.
This intent proof does not claim to verify a network's native transaction serialization.
A connector requiring that additional verification must provide it before its operation can activate.

The named `bounded_validity` default permits a five-minute proof lifetime with zero future-time tolerance.
An admitted profile may use a shorter interval. Enforce issued-at <= current UTC time < expires-at immediately before a new effect.
`current_key_trust` resolves the exact tenant/account/wallet/network/key binding through an authenticated provider adapter and approved account authority.
The key binding must identify its authority, revision, allowed scheme, validity and revocation state.
Never trust a key embedded only in the proof. Missing or stale binding, unresolved revocation or unsupported network refuses.
The trust resolver contract is new producer wiring; no existing account or finance digest establishes it.
EG authorization remains a separate decision resolved by the existing generated write-back contract.

Use the existing durable change-set identity and effect key as the replay fence; create no in-memory nonce authority.
Proof verification itself is read-only and consumes no grant. Reserve the effect atomically through the existing governed path.
The same accepted effect key and digest may return the prior authorized receipt; changed binding refuses.
Parallel submissions and restart must create at most one provider effect. Recheck current trust and expiry before a new effect.
If the existing durable producer cannot bind the proof to its authorization and reservation, report `verification_unavailable`.
That proof-binding extension is an explicit dependency; never manufacture a receipt or weaken generated schemas.

Decision: SDK owns cryptographic source verification, GraphOS consumes its fact, and EG remains the decision and durable record authority.
Rejected alternative: a GraphOS verifier or wallet-specific approval store, which duplicates the producer and weakens replay fencing.
Cross-repository consumer: GRAPHOS-DATA-MARKET-R007. Existing SDK-GOVERNED-WRITEBACK-R004 owns effect approval and idempotency.
References: [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) defines canonical JSON;
[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032) defines Ed25519. No research-paper derivation is claimed.


## Immutable intent and separate execution proof

This contract is shared by SDK-GOVERNED-WRITEBACK-R001 and GRAPHOS-DATA-MARKET-R007. All new wiring remains SPECIFIED.
`WalletBusinessIntent` is a closed JSON object with these exact required keys:
`schema_version`, `operation_id`, `connector_id`, `account_id`, `wallet_id`, `network_id`, `mode`, `action`,
`destination`, `asset_id`, `amount`, `business_terms`, `change_set_id`, `idempotency_key`.
`schema_version` is the string `1`; `mode` is `paper` or `live`.
All other fields are nonempty strings except `business_terms`, which is a closed object under the registered operation schema.
Amounts and all quantities, prices, fees and limits use exact decimal strings; no floating-point values are permitted.
An operation without a destination, asset or amount uses explicit null only where its registered schema permits no such effect.
`business_terms` includes every remaining effective argument, including position/order identity, side, order type, deadlines and fee limits when applicable.
The registered schema must account for every provider argument and every authority-related field. Executor defaults cannot add unconfirmed business intent.
Unknown fields, duplicate keys, invalid Unicode, unbounded values and schema mismatches refuse before preparation.
Nested JSON allows strings, booleans, null, arrays, objects and exactly representable integers; object keys are schema-defined ASCII.
No normalization or mutation occurs after preparation. A changed default or schema requires a new plan and confirmation.

The complete immutable binding projection is exactly `P = {"intent": WalletBusinessIntent}`.
`plan_digest` is the lowercase hexadecimal SHA-256 of UTF-8 serialization of P.
Serialization is exactly `json.dumps(P, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`.
P contains plain JSON values, so GraphOS `claim_values(P)` preserves them.
This equals existing `graph_os/api/invoke/plan.py:24` `params_digest(P)`; it is not the signature payload digest.
Both owners use this exact definition and shared cross-language vectors, including non-ASCII values, nested terms and decimal strings.
`bind_plan` also binds authenticated principal, tenant, policy revision, registry digest, operation, effect and confirmation mode.
These authority bindings remain mandatory. Intent account, destination, amount, network and mode always participate in the digest.
SDK reconstructs P from the immutable durable change set and matches the authenticated confirmed-plan binding before verification.
The durable change-set digest covers business intent and source versions, excluding proof, confirmation metadata and the derived plan digest.
Their durable association is separate metadata; the change set must never contain a digest of its own proof.

`WalletExecutionEnvelope` has exactly `phase`, `params`, `plan_ref`, `confirmation_ref`, `wallet_proof` and `idempotency_key`.
`params` equals P. The other members are execution metadata, never business parameters.
`phase` is `prepare`, `confirm` or `execute`; nullable references and proof are absent only when their phase permits.
HTTP uses this exact body. MCP adds these explicit properties beside `op`; its existing `execute` flag must agree with phase.
Confirm requires an explicit authenticated human action recorded by the existing durable authority; a client reference cannot assert confirmation.
`wallet_proof` is the SDK WalletProofRequest; its plan digest equals the definition above.
Proof tenant/actor must match authenticated authority; connector, operation, account, wallet and network must equal intent.
Proof nonce equals `change_set_id`; envelope, intent and proof idempotency keys must agree.
All proof metadata is verified, including signature, current trusted key, validity, change-set digest and confirmation association.
Separating proof from P permits later signing; it does not permit unsigned business fields or client-selected projection rules.
The canonical signed payload remains the existing domain-separated RFC 8785 profile, with `plan_digest` as a value.
No plan digest, confirmation reference or proof occurs inside P. Signature insertion therefore introduces no digest cycle.

The shared `WalletExecutionEnvelope` extension is missing and blocks activation of these operations.
HTTP `graph_os/api/http/routes.py:72` currently merges the entire JSON body into params before invocation at line 127.
For these registered operations, its new closed envelope parser must pass only envelope.params as operation parameters.
MCP `graph_os/api/mcp/verbs.py:26` PARAMETERS and `_invoke_and_render` at line 258 need explicit wallet proof and confirmation metadata.
The MCP `params` property must carry the same P as HTTP; duplicate or conflicting metadata refuses.
The shared Invoke contract must carry typed envelope metadata separately through confirmation and connector dispatch.
This is an explicit shared transport dependency, not an existing side channel or handler-level field removal.
`pipeline._effect` at line 218, `bind_plan` at line 230 and `EgPlanStore.validate` at plan.py:160 must use P unchanged.
`audit_event` at audit.py:28 and `_journal_binding` must use that same business projection and preserve all existing authority bindings.
Proof evidence joins by digest/reference separately; raw signatures must not enter logs or create a different business-effect identity.
Shared envelope validation must precede plan consumption; current `_effect` consumes a matching lease and lacks this proof-aware lifecycle.
Preparation and explicit confirmation must persist a binding without dispatching or consuming the execution lease.
Execution validates proof and confirmation before consuming that lease through the existing governed reservation path.
Failure, races and restart must retain existing durable fencing and reconciliation guarantees. Do not add another approval or nonce store.
Until envelope parsing, durable association and lifecycle wiring exist for both transports, refuse with UNAVAILABLE and no effect.
SDK maps unavailable binding to `verification_unavailable`; mismatched intent or proof bindings cannot become verification success.
