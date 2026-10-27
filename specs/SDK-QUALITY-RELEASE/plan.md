# Implementation design: portable quality and release

1. Inventory current hooks and classify each by source-only inputs versus environment-backed acceptance inputs. Preserve correctness and security checks with reproducible dependencies.
2. Remove stale copied-doc synchronization from PR critical path; consolidate maintained public guide source into the Pages build. Validate links and privacy on that source.
3. Provision scanner/tool versions and synthetic fixtures inside CI so cloud PRs reproduce the local source gate.
4. Build the SDK wheel and test an isolated installed consumer against the locked published graph wheel. Release and Pages jobs independently record artifact and URL evidence.

## R005 published-wheel provenance

Pin `epistemic-graph` to its PyPI wheels in `uv.lock`, by SHA-256. Forbid a
source build with `[tool.uv] no-build-package`. Bootstrap installs the locked
environment with `uv sync --frozen`. Graph inspection requires SDK-consumed
Python modules from the installed wheel package. The release record names one
locked wheel. Record graph and provenance fixtures only from this prepared
environment. Never synthesize installation evidence.

## Amendments

2026-10-27: Run CI and the manual fleet gates on the project interpreter in
`.python-version`. Remove the separate Python 3.12 PR job. Package metadata
continues to declare the existing Python support floor.
