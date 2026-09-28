# Test specification: repository transport

| ID | Action | Required assertion |
|---|---|---|
| RT-01 | Index a local two-commit fixture | Exact immutable revision/tree and per-file SHA-256 bind every page and receipt. |
| RT-02 | Rename, delete, and modify files | Correct tombstones, successor paths, changed blobs, and no duplicate outcome. |
| RT-03 | Change branch HEAD during fetch | Already-pinned revision remains consistent or operation refuses; never combines trees. |
| RT-04 | Feed traversal path, duplicate path, hash mismatch, cursor loop, or extra outcome | Typed refusal before complete receipt. |
| RT-05 | Simulate 401, expired reference, or provider identity mismatch | No anonymous fallback, secret leak, or cross-tenant cache reuse. |
| RT-06 | Return failed/unsupported parse for a blob | Result retains explicit disposition; later retry submits it again. |
| RT-07 | Compare batched and unbatched tree walk on public fixtures | Byte-identical manifest/outcomes; report cold/warm timings and object-read counts. |
| RT-08 | Submit to contributor-owned graph service | Durable receipt binds tenant/repository/revision/tree and all file dispositions; restart is idempotent. |

Offline PR gate: focused pytest plus repository hooks (Ruff, mypy, CCCC, Dupehound, KISS). RT-08 is environment-backed acceptance and must show **NOT RUN** until provisioned.
