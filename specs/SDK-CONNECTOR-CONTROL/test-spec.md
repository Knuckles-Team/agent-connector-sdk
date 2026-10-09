# Test specification: connector control

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-01 | Construct synthetic connector with valid manifest and registered entry point | Discovery selects exact group/name/distribution/version and server identity; direct and entry-point construction agree. |
| CC-02 | Change input schema, output schema, entry-point version, or server identity one at a time | Certification refuses each mismatch before tool execution. |
| CC-03 | Publish same canonical pack twice through a fake generated client | Same idempotency key and result; changed content yields new digest/key. |
| CC-04 | Feed duplicate entries, bad URI scheme, undeclared kind, literal credential, or oversized body | Deterministic named refusal; no pack call and no secret in output. |
| CC-05 | Request event/tool-choice proposal | Proposal can be logged and rejected; it cannot call write-back or grant an action. |
| CC-06 | Build wheel and install it in isolated environment with the locked published graph wheel | Generated DTO imports and client/pack calls work without source path overlays. |
| CC-07 | Scan every migrated connector batch | No runtime import or declared dependency on `agent_utilities`; SDK conformance suite and connector's own tests pass. |
| CC-08 | Submit one synthetic pack to a contributor-owned running graph service | Receipt binds tenant, connector, digest, and retry identity; wrong tenant and stale contract pin refuse. |
| CC-09 | Submit SQL change page with generated SourceIngest client | Typed receipt binds table/key/schema/checkpoint and advances only on accepted result; mismatched tenant or schema refuses. |
| CC-10 | Certify an annotated multi-modal pack | Capability, schema digests, modality, cost/latency units and provenance round-trip; missing estimate is unknown; malformed annotation refuses. |

Pull requests run `uv sync`, focused `pytest`, Ruff, mypy, wiring checks, CCCC, jscpd, Dupehound, and KISS through the repository's reproducible hooks. CC-08 is an acceptance probe, not a cloud-PR prerequisite. A missing optional live environment records **NOT RUN** rather than silently passing or failing the source gate.

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-11 | Parse a fake connector ontology with one `ac:AccessContract` and one `ac:PropertyBinding` (SDK-CONNECTOR-CONTROL-R021) | The parser returns one typed contract and its `VirtualMapping` fields. It refuses a literal secret, an unknown pushdown, pagination or access kind, a missing operation, and a non-integer hint. No error text contains the secret. |
| CC-12 | Scope a fake ontology that imports `http://knuckles.team/kg` and a sibling pack ontology. Prove the hub import leaves the body and appears in `requires_capabilities`. Prove an in-pack body keeps its bytes. (`tests/test_pack_ontology_imports.py`) | SDK-CONNECTOR-CONTROL-R022 |
| CC-13 | Capture a fake prompt with one required and one optional argument through `PromptArtifactKind.list_entries`. (`tests/test_prompt_content.py::test_prompt_capture_binds_required_arguments_as_template`) | `prompts/get` is awaited with `{"<required>": "{{<required>}}"}`; the stored `capture` records `kind: "template"` and the same binding map; `validate` accepts the entry; a prompt with no required argument still captures `kind: "rendered"` with an empty binding map. |
