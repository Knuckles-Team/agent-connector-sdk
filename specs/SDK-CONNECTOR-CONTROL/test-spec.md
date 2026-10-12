# Test specification: connector control

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-01 | Register a manifest-backed connector entry point | Check group, name, distribution, and version independently. Direct construction matches served server identity. |
| CC-02 | Change input schema, output schema, entry-point version, or server identity one at a time. | Certification refuses each mismatch before tool execution. |
| CC-03 | Publish same canonical pack twice through a fake generated client | Same idempotency key and result. Changed content yields new digest/key. |
| CC-04 | Feed duplicate entries, bad URI scheme, undeclared kind, literal credential, or oversized body | Deterministic named refusal. No pack call and no secret in output. |
| CC-05 | Request event/tool-choice proposal | Proposal can be logged and rejected; it cannot call write-back or grant an action. |
| CC-06 | Build wheel and install it in isolated environment with the locked published graph wheel | Generated DTO imports and client/pack calls work without source path overlays. |
| CC-07 | Scan every migrated connector batch | No runtime import or declared dependency on `agent_utilities`; SDK conformance suite and connector's own tests pass. |
| CC-08 | Submit one synthetic pack to a contributor-owned running graph service | Receipt binds tenant, connector, digest, and retry identity. Wrong tenant and stale contract pin refuse. |
| CC-09 | Submit SQL change page with generated SourceIngest client | Typed receipt binds table/key/schema/checkpoint and advances only on accepted result; mismatched tenant or schema refuses. |
| CC-10 | Certify an annotated multi-modal pack | Capability, schema digests, modality, cost/latency units and provenance round-trip. Missing estimate is unknown. Malformed annotation refuses. |

Pull requests run `uv sync`, focused `pytest`, Ruff, mypy, wiring checks, CCCC, jscpd, Dupehound, and KISS through the repository's reproducible hooks. CC-08 is an acceptance probe, not a cloud-PR prerequisite. When the optional live environment is absent, record that the probe did not run. Do not infer a source-gate result.

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-11 | Parse a fake connector ontology with one `ac:AccessContract` and one `ac:PropertyBinding` (SDK-CONNECTOR-CONTROL-R021) | The parser returns one typed contract and its `VirtualMapping` fields. It refuses a literal secret, an unknown pushdown, pagination or access kind, a missing operation, and a non-integer hint. No error text contains the secret. |
| CC-12 | Scope a fake ontology that imports `http://knuckles.team/kg` and a sibling pack ontology. Prove the hub import leaves the body and appears in `requires_capabilities`. Prove an in-pack body keeps its bytes. (`tests/test_pack_ontology_imports.py`) | SDK-CONNECTOR-CONTROL-R022 |
| CC-13 | Capture a fake prompt with one required and one optional argument through `PromptArtifactKind.list_entries`. (`tests/test_prompt_content.py::test_prompt_capture_binds_required_arguments_as_template`) | `prompts/get` is awaited with `{"<required>": "{{<required>}}"}`. The stored `capture` records `kind: "template"` and the same binding map. `validate` accepts the entry; a prompt with no required argument still captures `kind: "rendered"` with an empty binding map. |
| CC-14 | Simulate a typed required argument: `get_prompt` raises `McpPromptRejectedError` for a prompt with one required and one optional argument. (`tests/test_prompt_content.py::test_prompt_capture_falls_back_to_template_when_server_rejects_bound_argument`) | The capture still succeeds as `kind: "template"` with the same `bound_arguments` map. The stored `result` is a synthesized message naming the prompt's own arguments, not server content. `validate` accepts the entry. |
| CC-14b | Same failure for a prompt with no required argument. (`tests/test_prompt_content.py::test_prompt_capture_still_fails_when_rejected_with_no_required_argument`) | `McpPromptRejectedError` still raises; no fallback, because no placeholder was ever bound. |
| CC-14c | `get_prompt` raises the plain `McpTransportError` (a transport failure, not a protocol rejection) for a prompt with a required argument. (`tests/test_prompt_content.py::test_prompt_capture_propagates_genuine_transport_failures`) | `McpTransportError` still raises; the fallback never masks a server-unreachable failure. |
| CC-15 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.1. (`tests/test_tool_facts.py::test_facts_model_is_frozen_and_typed`) | Type `ToolContractFacts` holds as the row states. |
| CC-16 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.2. (`tests/test_tool_facts.py::test_side_effect_set_is_closed_and_read_only_is_consistent`) | Close the `SideEffect` set holds as the row states. |
| CC-17 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.3. (`tests/test_tool_facts.py::test_schema_tokens_uses_canonical_body_and_named_divisor`) | Compute `schema_tokens` from the existing canonical tool body holds as the row states. |
| CC-18 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.4. (`tests/test_tool_facts.py::test_undeclared_tool_defaults_to_not_read_only`) | Default to the safe value when a connector declares nothing holds as the row states. |
| CC-19 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.5. (`tests/test_tool_facts.py::test_mcp_read_only_hint_is_recorded_as_self_declared`) | Map MCP annotations as self-declared hints holds as the row states. |
| CC-20 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.6. (`tests/test_tool_facts.py::test_side_effects_round_trip_through_generated_pack_annotations`) | Read `side_effects` from `eg.annotations`, and gate on the generated type holds as the row states. |
| CC-21 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.7. (`tests/test_tool_facts.py::test_destructive_action_is_never_read_only`) | Reuse the destructive classification holds as the row states. |
| CC-22 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.8. (`tests/test_pack.py::test_tool_entry_pack_carries_contract_facts`) | Attach the facts to the captured tool entry holds as the row states. |
| CC-23 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.9. (`tests/test_certify_read_only.py::test_read_only_tool_with_recorded_write_fails_certification`) | Certify that a `read_only` tool wrote nothing in its recorded fixture holds as the row states. |
| CC-24 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.10. (`tests/test_certify_read_only.py::test_mcp_hint_without_fixture_is_unproven_and_unpinned`) | Refuse an unproven self-declared `read_only` holds as the row states. |
| CC-25 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.11. (`tests/test_certify_read_only.py::test_manifest_and_pack_carry_equal_facts`) | Generate the manifest facts and prove the path end to end holds as the row states. |
| CC-26 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.1. (`tests/test_auth_pkce.py::test_config_is_frozen_and_holds_reference_only`) | The model row holds as stated. |
| CC-27 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.2. (`tests/test_auth_pkce.py::test_authorize_exchanges_code_with_verifier`) | The behavior row holds as stated. |
| CC-28 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.3. (`tests/test_certify_options.py::test_pkce_option_selects_manager`) | The wiring row holds as stated. |
| CC-29 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.4. (`tests/test_auth_pkce.py::test_refusals_are_typed_and_leak_no_secret`) | The refusal row holds as stated. |
| CC-30 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.5. (`tests/test_auth_pkce.py::test_trace_record_has_no_secret_fields`) | The evidence row holds as stated. |
| CC-31 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.6. (`tests/test_certify_pkce_flow.py::test_certify_run_authenticates_through_pkce`) | The hot-path proof row holds as stated. |
| CC-32 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.1. (`tests/test_a2a_discovery.py::test_discovered_card_is_frozen_and_typed`) | The model row holds as stated. |
| CC-33 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.2. (`tests/test_a2a_discovery.py::test_fetch_uses_well_known_path_and_etag`) | The behavior row holds as stated. |
| CC-34 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.3. (`tests/test_vendor_extractors_archer_infra_a2a.py::test_base_url_entry_is_fetched_into_cards`) | The wiring row holds as stated. |
| CC-35 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.4. (`tests/test_a2a_discovery.py::test_refusals_write_nothing`) | The refusal row holds as stated. |
| CC-36 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.5. (`tests/test_a2a_discovery.py::test_entity_carries_fetch_provenance`) | The evidence row holds as stated. |
| CC-37 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.6. (`tests/test_vendor_extractors_archer_infra_a2a.py::test_extract_discovers_card_from_base_url`) | The hot-path proof row holds as stated. |
| CC-38 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.1. (`tests/test_readable_form.py::test_model_is_frozen_and_optional_on_facts`) | The model row holds as stated. |
| CC-39 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.2. (`tests/test_readable_form.py::test_render_is_bounded_plain_text`) | The behavior row holds as stated. |
| CC-40 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.3. (`tests/test_pack.py::test_tool_entry_carries_readable_form`) | The wiring row holds as stated. |
| CC-41 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.4. (`tests/test_certify_readable_form.py::test_unscored_form_is_refused`) | The refusal row holds as stated. |
| CC-42 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.5. (`tests/test_certify_readable_form.py::test_verdict_records_question_counts`) | The evidence row holds as stated. |
| CC-43 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.6. (`tests/test_certify_readable_form.py::test_certify_run_scores_form_and_pack_carries_it`) | The hot-path proof row holds as stated. |
| CC-44 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.1. (`tests/test_http_payments.py::test_models_are_frozen_and_typed`) | The model row holds as stated. |
| CC-45 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.2. (`tests/test_http_payments.py::test_decide_applies_named_limits`) | The behavior row holds as stated. |
| CC-46 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.3. (`tests/test_http_payments.py::test_client_hook_gates_402_through_approval`) | The wiring row holds as stated. |
| CC-47 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.4. (`tests/test_http_payments.py::test_refusals_send_no_payment_header`) | The refusal row holds as stated. |
| CC-48 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.5. (`tests/test_http_payments.py::test_every_attempt_emits_a_record`) | The evidence row holds as stated. |
| CC-49 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.6. (`tests/test_http_payments_flow.py::test_served_operation_pays_within_budget_and_refuses_over`) | The hot-path proof row holds as stated. |


## Served context acceptance

All cases below bind to SDK-CONNECTOR-CONTROL-R050 and its six children.
The planned test module is `tests/test_tool_context_served.py`.

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-50 | Construct context and progress models with malformed fields. | Unknown state, missing identity, NaN, negative completion and excessive message length refuse. |
| CC-51 | Two concurrent producers report completion `1`; after both finish, report `2`. Repeat with unknown total. Separately omit the token. | Emitted completion values are exactly `[1, 2]`; sequence strictly increases and completion never exceeds total. Equal-value updates may change the internal terminal summary. No token yields zero notifications and retains the terminal summary. |
| CC-52 | Start the SDK server with condensed and method registrars; call both over MCP | Each handler receives the authenticated context. Its dispatch, logs, progress and result retain one request identity. |
| CC-53 | Deny EG approval, expire deadline, cancel, and break progress delivery after a source effect. Reconnect after losing the terminal response. | Pre-effect refusal calls no backend. An uncertain result identifies the existing receipt. Governed reconciliation and retries produce at most one effect. Missing reconnect mapping returns `recovery_unavailable`, no reconstructed result and no second effect. |
| CC-54 | Run concurrent calls for two tenants and inspect logs, caches and results | No state or token crosses requests. Each event carries provenance; secrets, raw arguments and cached values are absent. |
| CC-55 | Run `test_served_context_progress_and_approval` against a running server and controlled backend | The client receives push notifications before terminal metadata. Backend counters prove allowed effects and zero denied effects. Direct helper invocation is insufficient. |

The served test must include stale and wrong-operation approval, mismatched tenant,
reused effect key with changed arguments. Also exercise duplicate requests and notification loss.
The served reconnect case must preserve the original request and effect identity across the disconnected sessions.
Exercise it with no authenticated producer mapping and assert the typed refusal before any repeated backend call.
Do not accept a helper-only refusal or an effect receipt as proof of terminal result retrieval.
Approval tests assert GraphOS returns EG's decision unchanged and the SDK refuses a mismatched binding.
Use bounded barriers to prove notification arrival before the backend completes.
Assert no messages arrive after terminal completion and cache state is cleared.
Record server revision, transport, exact command, result and redacted trace receipt.
These are implementation acceptance requirements; specification checks do not run them.


## Scoped credential and inline authorization acceptance

CC-56 through CC-61 bind SDK-CONNECTOR-CONTROL-R035.1 through R035.6 in tests/test_scoped_credential_transport.py.
Use a real served SDK connector, controlled local OIDC/provider servers and the qualified host challenge/vault fixture.
Enter tools/call with one granted client; assert exactly one credential resolution and authenticated provider request.
Repeat with a co-located unrelated client, wrong tenant, expired grant and revoked authority; assert zero resolver/provider calls.
Test environment and vault references equally; a failed vault grant cannot fall back to process-visible credentials.
For R046, invoke the actual certify command and the served connector's credential-missing path, not only PkceAuthManager directly.
Complete an S256 challenge through a real HTTP callback and read the host persistence receipt before observing the resumed request.
Test browser opening failure, callback failure, absent input, input timeout, cancellation, replay and wrong-client redirect submission.
Each case returns the named bounded outcome and creates no token exchange or resumed effect after invalidation.
Fail vault persistence after exchange; readiness must remain false. Restart and retry through current host authority without duplicating the pending operation.
Inspect transport and logs for codes, verifier, raw tokens, pasted responses and credential values. No public output may contain them.
These integration tests have not run. Helper tests and spec checks do not establish runtime completion.


### Served connector and token-profile acceptance

Extend the existing named served credential/PKCE tests through actual REST/MCP ingress, connector dispatch and controlled provider exchanges.
Grant connector A and prove its authorized call succeeds. Keep tenant, principal/client, provider, audience and scopes unchanged, then target connector B.
Caller-forged connector A metadata on B and a genuine B identity with only A's grant both refuse before secret resolution or exchange.
An explicit B grant permits B without changing A's authority. Assert challenge, vault receipt and transport evidence contain the admitted connector.
Use an OIDC provider returning a signed ID token plus opaque access and refresh tokens; the declared mixed profile must succeed.
Separately prove the JWT access-token profile succeeds with valid signatures, audiences, expiry and resource bindings.
Bad JWT signature, nonce, audience, issuer or expiry refuses; a JWT failure must never retry under an opaque profile.
For exchange-bound opaque tokens, validate authenticated provider/client/PKCE and required resource/account/consent evidence without manufacturing JWT claims.
For introspection-required opaque tokens, active and correctly bound evidence succeeds; inactive, unavailable or missing required fields refuses.
An opaque token without provider expiry may use only the explicit bounded host lease. Assert evidence distinguishes the two validity sources.
Forged profile selection, wrong connector, cross-tenant binding, excess scopes and unapproved resource audience all refuse with zero resumed effects.
The outbound opaque profile must not admit an unsigned GraphOS API bearer or remove its required tenant claim.
Inspect responses and logs for token/code leakage. These acceptance cases have not run. They require the runtime wiring.

<!-- spec-definition-patch:sdk5-r007-major-version-tests -->
## Major-version compatibility and pre-pin rollout acceptance (R007.1-R007.6)

These future tests have not run. The producer, gate, and writer attachments are not implemented; no VERIFIED evidence exists.

- **Model and inventory:** Assert stable canonical sorting and digest. Refuse duplicate, unidentifiable, or incomplete package inventories.
- **Receipt production:** Test every inventoried package against the exact artifact in isolation. Assert one complete bound receipt per package and unchanged dependency-file bytes.
- **Positive hot path:** Enter the production rollout command and exercise real pin writers. Assert the all-pass set authorizes only bound packages across R009-R013.
- **Incompatible hot path:** Fail one package check through the same entry point. Assert refusal before the first pin write and unchanged manifests and lockfiles.
- **Missing and stale evidence:** Remove a receipt or change the source, pin preimage, inventory, or artifact. Assert typed refusal and no pin changes.
- **Invalid receipt sets:** Test failed, incomplete, cancelled, duplicate, extra, and cross-package receipts. Assert preflight refusal before any write and byte-identical pins.
- **CC-105 / R007.4:** `tests/test_major_version_compatibility_served.py::test_fleet_preflight_refusal_preserves_all_pins` proves preflight refusal preserves every pin byte-for-byte.
- **CC-106 / R007.6:** `tests/test_major_version_compatibility_served.py::test_writer_b_preimage_race_reports_partial_rollout` races B after A writes. It proves B does not write and requires reconciliation. It identifies A as applied and B as refused.
- **Existing acceptance:** Retain R007 fingerprint and live-contract comparison and R009-R013 package migration and import-scan tests.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-primary-20261012-tests -->
## Consolidated SDK future acceptance
- **CC-81 / SDK-CONNECTOR-CONTROL-R051.1:** Validate all identity fields and actual instance IDs. Proposed: `tests/test_sandbox_provisioned_served.py::test_request_result_identity_round_trip`.
- **CC-82 / SDK-CONNECTOR-CONTROL-R051.2:** A replay returns the reconciled allocation without duplication. Proposed: `tests/test_sandbox_provisioned_served.py::test_uncertain_allocation_reconciles_before_retry`.
- **CC-83 / SDK-CONNECTOR-CONTROL-R051.3:** Exercise the served route, adapter, and result consumer. Proposed: `tests/test_sandbox_provisioned_served.py::test_agents_run_reaches_sdk_provisioner`.
- **CC-84 / SDK-CONNECTOR-CONTROL-R051.4:** Negative cases observe zero unsupported or unauthorized allocations. Proposed: `tests/test_sandbox_provisioned_served.py::test_denied_profiles_have_zero_provider_calls`.
- **CC-85 / SDK-CONNECTOR-CONTROL-R051.5:** Independent readback matches the bound allocation receipt. Proposed: `tests/test_sandbox_provisioned_served.py::test_receipt_matches_independent_readback`.
- **CC-86 / SDK-CONNECTOR-CONTROL-R051.6:** The served acceptance proves actual allocation and zero duplicate effects. Proposed: `tests/test_sandbox_provisioned_served.py::test_served_replay_has_no_duplicate_effect`.
- **CC-87 / SDK-CONNECTOR-CONTROL-R052.1:** Reject absent or malformed provenance and unbounded payloads. Proposed: `tests/test_visual_observation_served.py::test_rejects_unbound_or_unbounded_envelopes`.
- **CC-88 / SDK-CONNECTOR-CONTROL-R052.2:** The next step reads the committed same-run observation only. Proposed: `tests/test_visual_observation_served.py::test_next_step_reads_committed_same_run_reference`.
- **CC-89 / SDK-CONNECTOR-CONTROL-R052.3:** A served two-step test observes matching IDs at result, state, and consumer. Proposed: `tests/test_visual_observation_served.py::test_tools_call_forwards_observation_to_eg_and_au`.
- **CC-90 / SDK-CONNECTOR-CONTROL-R052.4:** Each refusal produces zero provider effects. Proposed: `tests/test_visual_observation_served.py::test_invalid_scope_refuses_before_provider_effect`.
- **CC-91 / SDK-CONNECTOR-CONTROL-R052.5:** EG readback confirms provenance without returning raw content. Proposed: `tests/test_visual_observation_served.py::test_readback_excludes_visual_payload`.
- **CC-92 / SDK-CONNECTOR-CONTROL-R052.6:** The observed path proves reuse and zero effects on refusal. Proposed: `tests/test_visual_observation_served.py::test_two_step_reuse_isolation_and_stale_refusal`.
- **CC-93 / SDK-CONNECTOR-CONTROL-R053.1:** Reject duplicate declarations, literals, and unknown components. Proposed: `tests/test_environment_manifest_served.py::test_manifest_rejects_duplicate_literal_and_unknown_entries`.
- **CC-94 / SDK-CONNECTOR-CONTROL-R053.2:** Undeclared reads and missing required declarations block startup. Proposed: `tests/test_environment_manifest_served.py::test_missing_and_undeclared_inputs_block_startup`.
- **CC-95 / SDK-CONNECTOR-CONTROL-R053.3:** The served launcher consumes the SDK declaration set. Proposed: `tests/test_environment_manifest_served.py::test_host_startup_consumes_sdk_declaration_set`.
- **CC-96 / SDK-CONNECTOR-CONTROL-R053.4:** A secret canary is absent from every refusal diagnostic. Proposed: `tests/test_environment_manifest_served.py::test_refusal_diagnostics_redact_secret_values`.
- **CC-97 / SDK-CONNECTOR-CONTROL-R053.5:** Independent readback reproduces the declaration set and decision. Proposed: `tests/test_environment_manifest_served.py::test_readback_matches_manifest_and_decision`.
- **CC-98 / SDK-CONNECTOR-CONTROL-R053.6:** The healthy case serves; each negative case refuses before admission. Proposed: `tests/test_environment_manifest_served.py::test_served_startup_accepts_declared_and_refuses_invalid`.
- **CC-99 / SDK-CONNECTOR-CONTROL-R054.1:** The inventory covers every loader before migration. Proposed: `tests/test_json_tag_loader_migration_served.py::test_inventory_finds_every_source_loader`.
- **CC-100 / SDK-CONNECTOR-CONTROL-R054.2:** Served operations and schemas remain equivalent. Proposed: `tests/test_json_tag_loader_migration_served.py::test_registered_operations_match_source_schemas`.
- **CC-101 / SDK-CONNECTOR-CONTROL-R054.3:** Tests reach real registration, dispatch, and backend. Proposed: `tests/test_json_tag_loader_migration_served.py::test_tools_list_and_call_reach_backend`.
- **CC-102 / SDK-CONNECTOR-CONTROL-R054.4:** Negative calls retain typed refusal and zero backend effects. Proposed: `tests/test_json_tag_loader_migration_served.py::test_denied_malformed_and_unknown_calls_have_zero_effects`.
- **CC-103 / SDK-CONNECTOR-CONTROL-R054.5:** Reconstruct the parity decision from recorded digests and results. Proposed: `tests/test_json_tag_loader_migration_served.py::test_parity_receipt_reconstructs_from_digests`.
- **CC-104 / SDK-CONNECTOR-CONTROL-R054.6:** The acceptance proves dispatch parity and no opt-in regression. Proposed: `tests/test_json_tag_loader_migration_served.py::test_default_and_opt_ins_preserve_dispatch_parity`.

These are required future tests. None ran during definition authoring.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-r054-root-test-20261012 -->

- **CC-80 / SDK-CONNECTOR-CONTROL-R054:** Compare every inventory entry with its served Python surface. Cover each parity and refusal child. Require independent readback before completion.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-r054-binding-marker-20261012 -->

<!-- # spec: SDK-CONNECTOR-CONTROL-R054; planned acceptance link only. -->
<!-- /spec-definition-patch -->
