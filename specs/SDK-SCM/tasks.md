# Tasks: source client and virtual workspace

Governing spec: [spec.md](spec.md). Design: [plan.md](plan.md). Rows:
[requirements.md](requirements.md).

- [ ] Inventory the served `source.*` operations, their wire types, and the
  repository-manager connector's development tools; record the exact
  operation set the client binds (SDK-SCM-R001).
- [ ] Implement the typed source client module with one frozen method per
  operation and stable continuations (SDK-SCM-R001.1).
- [ ] Implement bounded digest-keyed blob caching with named bounds,
  LRU eviction, and digest verification on read (SDK-SCM-R001.2).
- [ ] Wire the client behind the repository-manager connector's served
  development tools inside arbora MCP and behind a host-side composition
  (SDK-SCM-R001.3).
- [ ] Close the refusal set with typed reasons and prove zero-effect refusals
  (SDK-SCM-R001.4).
- [ ] Bind provenance to every result and cache event without secret values
  (SDK-SCM-R001.5).
- [ ] Prove the served read and conflict path through the registered tool
  (SDK-SCM-R001.6).
- [ ] Implement the virtual workspace mount state, entries, and pending
  changeset models (SDK-SCM-R002.1).
- [ ] Implement lazy directory resolution, materializing reads, write
  accumulation, and flush-as-one-commit (SDK-SCM-R002.2).
- [ ] Wire the mount over the client with the FUSE default and overlay
  copy-up backends; prove no clone or checkout runs behind it
  (SDK-SCM-R002.3).
- [ ] Close the mount refusal set: unadmitted client, unknown prefix,
  traversal and symlink escape, and the changed-base conflict
  (SDK-SCM-R002.4).
- [ ] Bind mount and flush evidence to receipts without secret values
  (SDK-SCM-R002.5).
- [ ] Prove the served mount read/write/conflicting-flush path through the
  registered tool (SDK-SCM-R002.6).
- [ ] Record exact merged commits, CI runs, and served test receipts in
  `spec.md` before any row may leave SPECIFIED.
