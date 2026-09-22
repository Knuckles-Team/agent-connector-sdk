# Quality gates

The tracked hook configuration is `.config/pre-commit.yaml`. Pushes run bounded
format, lint, lock-consistency, and patch-safety checks. Full tests, package
builds, dependency readiness, scanner versions and differential/census checks,
and the exhaustive CI replica run manually or in hosted CI.
CI runs the release-critical subset in `.github/workflows/release.yml`.

## Scanners

| Scanner | Version | Scope | Rule |
|---|---|---|---|
| cccc | 1.6.0 | staged package Python | no new or worsened function above cyclomatic 10 or cognitive 15 |
| KISS | 0.4.10 | staged package Python | `.kiss/kiss.toml`, findings attributable to the diff |
| dupehound | 0.1.2 | changed functions | no new function clones |
| jscpd | 5.0.16 | pushed range and full tree | no new copied blocks; census printed |
| scanner census | cccc and KISS | every package module | zero findings, absolutely |

Scanner versions are verified before each run; a missing or different binary
stops the gate rather than passing it.

## Wiring

| Gate | Fails when |
|---|---|
| orphan modules | a package module is reachable from no public module, entry point or import |
| public API tested | a public name is used by no test |

## Other gates

Secret history, the security and garbage sanitizer, tracked privacy, root
hygiene, `.gitignore` convergence, OSV dependency audit, `uv lock --locked`,
supply-chain pinning, the phase-direction check, stubs, environment reads outside
`config.py`, stdout writes in served code, swallowed errors, import cycles,
event-loop blocking, ruff, mypy (strict), bandit, codespell, vulture, the test
suite, the strict site build, the wheel build, and a replay of the CI jobs.

The `public-surface` gate validates the README badge set, required public
headings, Pages link, local links, document size, current-state language, and the
durable `AGENTS.md` structure. Its repository identity is configured in
`[tool.pipelines_hooks.public_surface]`.

No graph-boundary stub is allowed. SourceIngest, ConnectorPack, and WriteBack
must use epistemic-graph's generated contracts and clients, and readiness must
fail closed when required verified authority has not been injected.
