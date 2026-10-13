# Implementation design: portable quality and release

1. Inventory current hooks and classify each by source-only inputs versus environment-backed acceptance inputs. Preserve correctness and security checks with reproducible dependencies.
2. Remove stale copied-doc synchronization from PR critical path; consolidate maintained public guide source into the Pages build. Validate links and privacy on that source.
3. Provision scanner/tool versions and synthetic fixtures inside CI so cloud PRs reproduce the local source gate.
4. Build the SDK wheel and test an isolated installed consumer against the locked published graph wheel. Release and Pages jobs independently record artifact and URL evidence.

## R005 pinned source and release-wheel provenance

Bootstrap pins the EG contract checkout to the commit named in
`scripts/epistemic_graph_release.json`. Lock resolution preserves the declared
dependency versions. Install the wheel only when its SHA-256 matches that
release record. Use `--no-deps` so wheel installation cannot alter the lock.
Graph inspection requires SDK-consumed Python modules from that exact checkout.
Distribution metadata and package files must match the same wheel. Record graph
and provenance fixtures only from this prepared source-plus-wheel environment.
Never synthesize installation evidence.
