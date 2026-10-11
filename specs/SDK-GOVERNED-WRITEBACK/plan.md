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
