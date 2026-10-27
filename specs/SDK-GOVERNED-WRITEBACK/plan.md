# Implementation design: governed write-back

1. Preserve generated graph types and the current `WriteBackPort`, `GovernedWriteBack`, `DurableWritableConnector`, transport and `WriteBackLedger` composition.
2. Bind audit reservation and deterministic approval to the exact canonical digest and source version before mutation. Keep proposal evaluation separate.
3. Add a synthetic writable adapter with explicit prior-effect and reconciliation semantics; then migrate one real vendor adapter using its business API.
4. Exercise crash boundaries before source effect, after effect before receipt, and after receipt before response. Restart must recover from graph-owned receipts.
5. Publish redacted approval, attempt and reconciliation evidence only after the cross-process probe passes; then widen adapter support in small slices.


## Wallet signature verification (SDK-GOVERNED-WRITEBACK-R001)

Data flow: Arbora confirmed plan -> authenticated connector operation -> SDK verifier -> existing authorization/audit -> source effect -> durable receipt.
Existing code: `GovernedWriteBack.apply` (`agent_connector_sdk/writeback/service.py:74`) resolves authorization and reserves audit before transport apply.
`DurableWritableConnector.apply` (`agent_connector_sdk/writeback/connector.py:75`) reads durable prior effects; its reconciliation path handles uncertainty.
Reachable today: no wallet verification path exists. The ordinary governed apply composition is reachable.
Add one shared verifier and a typed proof input to that composition; do not duplicate authorization or replay storage.
Expose the verifier through the admitted connector's authenticated operation so Arbora imports one SDK contract, not cryptographic code.
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

Decision: SDK owns cryptographic source verification, Arbora consumes its fact, and EG remains the decision and durable record authority.
Rejected alternative: an Arbora verifier or wallet-specific approval store, which duplicates the producer and weakens replay fencing.
Cross-repository consumer: ARBORA-DATA-MARKET-R007. Existing SDK-GOVERNED-WRITEBACK-R004 owns effect approval and idempotency.
References: [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) defines canonical JSON;
[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032) defines Ed25519. No research-paper derivation is claimed.


## Immutable intent and separate execution proof

This contract is shared by SDK-GOVERNED-WRITEBACK-R001 and ARBORA-DATA-MARKET-R007. The proof transport wiring has not been implemented.
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
P contains plain JSON values, so Arbora `claim_values(P)` preserves them.
This equals existing `arbora/api/invoke/plan.py:24` `params_digest(P)`; it is not the signature payload digest.
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
HTTP `arbora/api/http/routes.py:72` currently merges the entire JSON body into params before invocation at line 127.
For these registered operations, its new closed envelope parser must pass only envelope.params as operation parameters.
MCP `arbora/api/mcp/verbs.py:26` PARAMETERS and `_invoke_and_render` at line 258 need explicit wallet proof and confirmation metadata.
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


## Repository source effects (SDK-GOVERNED-WRITEBACK-R004)

### Existing seams and missing production path

`agent_connector_sdk/ports/writeback.py` already defines current_version, dry_run, apply and reconcile. `GovernedWriteBack.apply` in `agent_connector_sdk/writeback/service.py` validates the canonical set and reads prior effects and current version. It verifies authorization, reserves audit, then invokes `WriteBackTransport.apply(change_set, expected_version)`. `DurableWritableConnector.apply` in `agent_connector_sdk/writeback/connector.py` reads graph receipts and records attempts. These are integration seams, not proof of a production repository writer. A preflight version verification alone cannot prevent a later conflicting write. The current service discards the reservation ID returned by reserve.

Add the proposed SDK-only contracts in `agent_connector_sdk/writeback/repository_effect.py` and export them through the existing SDK contract surface. An admitted provider transport must implement the existing `agent_connector_sdk/ports/writeback_transport.py`. Before activation, evidence must name its production module and registered operation ID. Do not invent a current Git adapter or operation. Reuse the existing operation phases `WriteBackPort.dry_run`, `apply` and `reconcile`; no new approval authority or ingestion write route is permitted.

### Closed request and generated change-set projection

`RepositorySourceEffectIntent` version 1 has exactly these required fields:

| Field | Required meaning |
|---|---|
| schema_version | Integer 1. |
| repository_id | Stable provider repository identity resolved within trusted connector configuration. No client-selected endpoint or credential. |
| target_ref | Exact permitted update target within that repository; a mutable target name never substitutes for the immutable base. |
| relative_path | Exact UTF-8 repository-relative regular-file path with nonempty slash-separated segments. |
| base_revision | Complete immutable provider revision against which the target is conditionally updated. Reject abbreviated or mutable aliases as the base. |
| expected_file_digest | Lowercase SHA-256 of existing exact file bytes, or null for an approved creation only. |
| expected_executable | Boolean for an existing regular file, or null for creation. |
| action | `create` or `update`; deletion, rename, link and directory operations are outside this profile and refuse. |
| payload_base64 | Canonical padded base64 of all desired bytes, including final newline and encoding bytes. No implicit encoding conversion. |
| payload_sha256 | Lowercase 64-character SHA-256 of the decoded payload. |
| payload_size | Nonnegative integer equal to decoded byte count, within the trusted adapter profile limit. |
| executable | Boolean desired executable mode; no other object mode is admitted. |
| adapter_contract_digest | Pinned admitted adapter schema/capability digest, including size and path rules. |

`RepositorySourceEffectRequest` is a closed SDK object with exactly three members. They are `schema_version` (1), `change_set` (generated SourceChangeSet) and `intent` (the object above). It adds no caller-asserted approval or actor outside the generated change set. Resolve actual caller identity and connector binding from the existing authenticated operation context. Compare them with the durable set; refuse substitution.

Use `desired_patch = {"repository_effect": intent}` and `field_scope = ["repository_effect"]` with the matching field_provenance entry in the generated change set. The registered adapter must explicitly admit this field; generic arbitrary fields are not repository permission. Require `request.intent == durable.desired_patch["repository_effect"]` exactly. Set source_instance_id to the trusted provider installation and entity_id to the stable repository identity. Set base_source_version to intent.base_revision and connector_id to the admitted connector. Retain existing verification for tenant_id, actor, purpose, capability, policy digest and expiry. Preserve authorization contract digests, authorization reference and idempotency key. Approval binds the resulting complete change_set_digest. Use the generated canonical_digest and patch_digest functions unchanged, not a parallel hash formula. The pinned generated contract supports a JSON desired_patch; SDK must not fork its schema.

No provider-effective argument may come from an unbound executor default. Any required provider option must be fixed by the admitted contract or included in the approved intent before activation. Extra fields, duplicate JSON keys, invalid Unicode, inconsistent null states, unsupported versions and noncanonical base64 refuse. Preview must disclose exact target, path, base, old/new byte digests and sizes, mode and all provider-effective options. It performs no mutation. Full bytes remain in the authorized change set and preview access boundary, not public logs.

### Scope, approval and effect boundary

Resolve repository identity and allowed targets/paths from existing trusted connector configuration and authenticated scope. A request cannot select a provider URL, credential, local checkout root or broader scope. Reject absolute paths, empty/dot/parent segments, backslashes, NUL, drive/URI prefixes and encoded separator/traversal aliases that a provider may reinterpret. Do not silently normalize a different path into the approved path. Resolve the immutable tree and reject symlink traversal, alias collisions and non-regular targets; confirm the provider addresses that same path. Recheck the binding immediately before a new effect.

The existing authorization resolver must yield an approval bound to this exact durable change-set digest. Verify caller/tenant, contract pin, expiry, target/path scope, immutable base, exact bytes and file mode before mutation. Retain the actual AuditReservationPort reservation ID. Bind it to the same change set and effect key; verify success before invoking the provider. A preview, proposal, ingestion cache, prompt export, or asserted `applied=true` cannot authorize an effect.

Use the provider's business-rule API with atomic expected-base and file-state conditions. An API may return a new immutable object followed by a conditional target update. It must preserve approved intent and prevent unapproved target changes. If the provider cannot guarantee equivalent conditional semantics, refuse as unsupported before mutation. A base change between read_current and apply must be rejected at the provider, not overwritten. No force push, unconditional retry, database write or local filesystem fallback is permitted. Provider branch protections and other business rules remain in force.

### Receipt and durable reconstruction

`RepositorySourceEffectReceipt` is a closed version-1 object. Its exact members are:

- schema_version, tenant_id, actor, connector_id, source_instance_id;
- repository_id, target_ref, relative_path, base_revision;
- change_set_id, change_set_digest, idempotency_key;
- approval_ref, approval_decision_digest, audit_reservation_id, adapter_contract_digest;
- effect_revision, readback_sha256, readback_size, executable.

 Every identity comes from the durable approved set or trusted producer evidence. `effect_revision` is the actual complete immutable provider revision; never the requested key, base, target name or a fabricated identifier. `readback_sha256` and readback_size come from a separate provider read at effect_revision, not an echoed mutation body. Require readback bytes and mode to equal the approved payload exactly.

Define receipt_digest as lowercase SHA-256 of the UTF-8 JSON serialization. Use sorted keys, compact separators, ensure_ascii=False and allow_nan=False. The receipt contains only strings, booleans and bounded exact integers; no timestamps or transient fields change it during replay. Store receipt_digest in the existing WriteBackAttempt.connector_observation_digest. Store the actual effect revision in post_source_version and the approved immutable base in pre_source_version. Store generated patch_digest in applied_field_digest. Preserve existing authorization input/output and provenance digests. Only record an applied successful attempt after independent readback matches; append it through WriteBackLedger before reporting success.

Reconstruct the identical receipt from the durable canonical change set and original applied attempt. Recover the stable audit reservation for its key and original readback values committed by connector_observation_digest. Approved payload digest/size/mode are those original readback values only after that successful attempt exists. Recompute receipt_digest and require equality with the durable observation digest; never infer an applied attempt from expected payload values. Provider revision readback can independently confirm that persisted claim. Recovery of the stable audit reservation and every bound value is an implementation prerequisite. Missing values cannot produce a receipt. The existing service must retain that reservation binding and preserve it across receipt reconstruction. No SDK-local approval or receipt database replaces the graph ledger.

After a possible mutation, readback failure, lost response or failed ledger append means uncertainty. This also applies without a graph attempt receipt. Recovery must interrogate the provider using a durable request/effect identity and immutable history. Fence concurrent attempts through the existing governed authority before retry. Matching bytes at the current target alone cannot distinguish this request from another writer. If the adapter cannot prove causality and conditional no-effect, keep the outcome unresolved. A proven effect recovers its original revision and readback before recording the existing reconciliation result. Authoritative no-effect permits only another conditional attempt against the still-approved base. New base or payload requires new preview and approval.

### Delivery order and consumer handoff

Keep R004.1–R004.4 as independent generic residual units. Then implement request validation (R004.5), path resolution (R004.6), approved composition (R004.7), provider compare-and-apply (R004.8), receipt binding (R004.9), readback (R004.10), reconciliation (R004.11), and served composition (R004.12). Each unit has one proposed acceptance function in test-spec.md. No generic helper test alone proves a production provider effect.

### Amendment 2026-10-27: reservation identifier guard

`GovernedWriteBack.apply` must refuse a missing or blank reservation ID before
calling the transport. The file-backed sink reservation compares an existing
ID to the exact expected key and digest. R004.3 adds the typed binding and
the separate durable reservation proof.

### Amendment 2026-10-27: uncertain reconciliation

`GovernedWriteBack.reconcile` rejects an uncertain result that permits retry.
The guard matches the durable receipt rule and retains the unresolved state.
R004.2 retains its separate cross-process replay and served proof.

Arbora consumes these exact request/receipt contracts under ARBORA-FLEET-R003, using ARBORA-OPS-R009's existing invoke authority. Its producer-composition definition must wait for the SDK definition to merge. EG-TYPED-PACKS-R094.7 can name both after their definitions merge. EG-TYPED-PACKS-R002.10 still requires a separately coordinated AU model-dispatch consumer; source write-back does not meet that requirement. No candidate accounting change or runtime completion follows from these definitions.
# Amendment: durable applied receipts are terminal

For SDK-GOVERNED-WRITEBACK-R004.2, receipt replay must reject a later
non-applied state after an applied receipt, including across receipt pages.
Reject a contradictory no-effect observation to prevent another mutation.

# Amendment: receipt continuation must not skip records

For SDK-GOVERNED-WRITEBACK-R004.2, a receipt page with a continuation must
contain at least one receipt. Its continuation equals the last receipt's
sequence. Replay rejects a cursor that can skip unseen durable records.
# Bound audit reservations

R004.3 uses a typed reservation carrying its ID, effect key and change-set
digest. The governed apply path verifies all three before a source mutation.
The file adapter serializes reservations and synchronizes the stored record.
Existing file records are accepted only when their ID binds the same key and
digest. External audit adapters must return the same typed binding.

## Exact dry-run display

SDK-GOVERNED-WRITEBACK-R004.15 binds each displayed preview to the validated current snapshot and approved patch. Compare JSON values by their serialized type and value, not Python equality that equates booleans and integers. This remains independent of repository provider composition.
