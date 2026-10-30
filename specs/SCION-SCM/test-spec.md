# Test specification: source client and virtual workspace

Governing spec: [spec.md](spec.md).

| ID | Setup | Required assertion |
|---|---|---|
| SC-01 | Source client against a controlled served `source.*` backend. | `tree` returns one bounded page with a continuation; the next page resumes without re-reading the first. |
| SC-02 | Blob read, warm and cold, same served digest. | Cold read fetches through the served operation; warm read serves from the local cache. Both agree on digest and bytes. |
| SC-03 | Cache exceeds its entry-count and byte bounds | Eviction removes least-recently-used entries. Evicted digests re-fetch on demand. Bounds are the named defaults unless lowered. |
| SC-04 | Served digest differs from the cached digest for one entry. | The entry is evicted and re-read through the served operation. No stale bytes reach the caller. |
| SC-05 | Identical commit retry after simulated transport loss. | The retry reuses the same operation identity and returns the same accepted receipt. No second write effect occurs. |
| SC-06 | `unauthorized`, `not_found`, `conflict`, `path_denied`, `oversized`, `deadline_exceeded`, `transport_unavailable` refusals | Each refusal is typed with its closed reason code. Every refused write makes zero effects and advances no revision. |
| SC-07 | Mount over the client for declared prefixes; read inside and outside them | Inside-prefix reads materialize exact bytes. Outside-prefix reads refuse with a typed reason and fetch nothing. |
| SC-08 | Write three paths, then flush; a second flush after a conflicting base change. | The first flush submits exactly one changeset with the accepted commit receipt. The second flush returns `conflict` and leaves the pending changeset intact. |

The planned modules are `tests/test_source_client.py`,
`tests/test_source_mount.py`, `tests/test_source_client_served.py`, and
`tests/test_source_mount_served.py`. All cases are planned and unexecuted;
none of them establish runtime acceptance until the implementation lands.

## Source client acceptance (SCION-SCM-R001)

| Requirement | Case | Required assertion |
|---|---|---|
| `SCION-SCM-R001.1` | Model | `tests/test_source_client.py::test_request_and_page_models_are_typed_and_frozen` refuses untyped payloads and unknown continuation fields. |
| `SCION-SCM-R001.2` | Behavior | SC-01 through SC-05. `tests/test_source_client.py::test_cache_is_bounded_and_digest_checked` and `tests/test_source_client.py::test_retry_reuses_operation_identity`. |
| `SCION-SCM-R001.3` | Wiring | `tests/test_source_client_served.py::test_connector_tool_composes_the_client` enters the registered development tool and observes the client call. |
| `SCION-SCM-R001.4` | Refusal | SC-06. `tests/test_source_client.py::test_refusals_are_typed_and_zero_effect`. |
| `SCION-SCM-R001.5` | Evidence | `tests/test_source_client.py::test_results_bind_provenance_without_secrets`; a log inspection proves no credential value, secret value, or private path appears. |
| `SCION-SCM-R001.6` | Hot-path proof | SC-02 and SC-06 through the served path: `tests/test_source_client_served.py::test_served_client_pages_and_conflict_refusal`. |

## Virtual workspace acceptance (SCION-SCM-R002)

| Requirement | Case | Required assertion |
|---|---|---|
| `SCION-SCM-R002.1` | Model | `tests/test_source_mount.py::test_mount_state_and_entry_models_are_typed` refuses an unknown prefix at mount time. |
| `SCION-SCM-R002.2` | Behavior | SC-07 and SC-08. `tests/test_source_mount.py::test_reads_materialize_and_writes_accumulate`. |
| `SCION-SCM-R002.3` | Wiring | `tests/test_source_mount.py::test_mount_composes_the_source_client`; a source scan proves no clone, object database, or checkout step runs behind the mount. |
| `SCION-SCM-R002.4` | Refusal | SC-08 conflict case; `tests/test_source_mount.py::test_refusals_preserve_pending_changeset` covers traversal and symlink escape with zero effects outside the root. |
| `SCION-SCM-R002.5` | Evidence | `tests/test_source_mount.py::test_mount_events_bind_receipts_without_secrets`; flush events bind the commit receipt and per-path outcomes. |
| `SCION-SCM-R002.6` | Hot-path proof | SC-07 and SC-08 through the served path: `tests/test_source_mount_served.py::test_served_mount_read_write_and_conflicting_flush`. |

## Negative and boundary cases

Invalid prefix sets, empty mount roots, zero-byte and over-bounded blobs,
and a changed base revision between write and flush. A transport loss
mid-flush and a cache entry with corrupted bytes complete the set. Each
case produces its typed refusal or re-read, keeps the pending changeset
intact, and makes zero unauthorized effects.

## Quality and release proof

Run the focused client tests: `uv run --frozen python -m pytest -q tests/test_source_client*`.
Run the mount tests: `uv run --frozen python -m pytest -q tests/test_source_mount*`.
Run strict mypy over `scion_sdk`.
Run Ruff check and format over the changed files.
Run the spec gates `spec-standard`, `spec-decomposition`, `spec-status`, and `spec-trailers` through `pipelines-hook`.
Record the exact source revision, the command output, and the served test receipts for each acceptance run.
A source test alone is not served acceptance.
The served cases require the real connector tool path.
