# Test specification: portable quality and release

| ID | Probe | Required assertion |
|---|---|---|
| QR-01 | Fresh clone with only declared toolchain and lock | Offline source gate starts and gives deterministic pass/fail. No sibling checkout or live service required. |
| QR-02 | Planted private IP, host alias, credential, machine path and environment domain in doc fixture | Privacy scanner fails each while permitting documentation-safe example addresses. |
| QR-03 | Edit public API/Pages source | Link/nav/build checks see the maintained source. Stale copied documentation cannot block unrelated source work. |
| QR-04 | Build wheel then install in isolated environment | SDK imports and generated graph DTO contract work without repository source overlay. |
| QR-05 | Run release with absent online service or entitlement | Source gate remains truthful; acceptance reports `NOT RUN` and release remains unpublished. |
| QR-06 | Publish Pages and wheel from exact approved commit | Page URL, wheel digest, tag and CI run all bind same commit. |
| QR-07 | EG from published PyPI wheels | Require a registry source with hashed wheels and no source distribution in `uv.lock`. Require `no-build-package` for EG in `pyproject.toml`. Require the release record to name a locked wheel, and the installed version to match the lock. Require SDK-consumed contract modules to resolve inside the installed wheel. Reject Git sources, source distributions, unhashed wheels, overlays, outside origins, wrong versions, metadata drift, or missing dependencies. |
| QR-08 | Runtime extras | Traverse requested client/server and email extras with transitive dependencies. Read requirements from distribution metadata. Match active dependencies to `uv.lock`. Fail if metadata for an active locked dependency is missing. Exclude unrequested extras. |

Source PR checks include pytest, Ruff, mypy, CCCC, KISS, Dupehound, jscpd, wiring, privacy and package build. QR-06 belongs to release acceptance and must not be a prerequisite for a cloud pull request.

## SCION-QUALITY-RELEASE-R005.1

`tests/test_conformance_plugin.py` runs every check against a conforming fixture. It breaks the ontology, version, fleet name, provider entry point and sources properties one at a time. A subprocess run in a fixture repository reports one passing test per check. A run without the declaration adds no test. A run with an explicit node id adds none.

- **R005 workspace-local cache:** `tests/gates/test_workflow_contract.py::test_gates_uv_cache_is_workspace_local_and_job_scoped` checks the shared workflow input and ignored cache path. After the shared input is available, compare runner device IDs and a hardlink probe. Compare `uv sync` times for serial and concurrent runs.
