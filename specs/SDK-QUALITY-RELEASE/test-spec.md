# Test specification: portable quality and release

| ID | Probe | Required assertion |
|---|---|---|
| QR-01 | Fresh clone with only declared toolchain and lock | Offline source gate starts and gives deterministic pass/fail; no sibling checkout or live service required. |
| QR-02 | Planted private IP, host alias, credential, machine path and environment domain in doc fixture | Privacy scanner fails each while permitting documentation-safe example addresses. |
| QR-03 | Edit public API/Pages source | Link/nav/build checks see the maintained source; stale copied documentation cannot block unrelated source work. |
| QR-04 | Build wheel then install in isolated environment | SDK imports and generated graph DTO contract work without repository source overlay. |
| QR-05 | Run release with absent online service or entitlement | Source gate remains truthful; acceptance reports `NOT RUN` and release remains unpublished. |
| QR-06 | Publish Pages and wheel from exact approved commit | Page URL, wheel digest, tag and CI run all bind same commit. |

Source PR checks include pytest, Ruff, mypy, CCCC, KISS, Dupehound, jscpd, wiring, privacy and package build. QR-06 belongs to release acceptance and must not be a prerequisite for a cloud pull request.
