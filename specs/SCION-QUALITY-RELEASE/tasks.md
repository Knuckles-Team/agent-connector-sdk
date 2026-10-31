# Tasks: portable quality and release

- [x] Replace the stale documentation-copy gate with one maintained Pages source. Add portable validation. Align the public README and site to the task-first order (SCION-QUALITY-RELEASE-R004).
- [x] Prove privacy scanner red on planted violations (SCION-QUALITY-RELEASE-R002).
- [x] Qualify cloud PR source gate from a fresh clone with no live environment, built under the pinned managed Python toolchain declared in `pyproject.toml` (SCION-QUALITY-RELEASE-R003).
- [x] Bind published graph wheel, SDK wheel, Pages site and exact commit (SCION-QUALITY-RELEASE-R001).
- [x] Confirm the locally pinned install command reproduces hosted CI's exact dependency import graph (SCION-QUALITY-RELEASE-R005).
- [x] Bind the EG release source, wheel, import origins, and requested extras under R005. Record the graph only after positive and negative probes pass.
- [x] Generate connector conformance tests from the declared connector with a pytest plugin (SCION-QUALITY-RELEASE-R005.1).
- [x] Move metric scanners from CI to the weekly shared advisory workflow (SCION-QUALITY-RELEASE-R006).
