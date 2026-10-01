# Quality gates

The tracked hook configuration is `.config/pre-commit.yaml`, and hosted CI
(`.github/workflows/release.yml`) runs that same file: its whole pre-commit
stage, then its pre-push stage (tests, wheel build, secret history, patch
safety). Native scanners, tracked privacy, and the fleet dependency gates are in
the manual stage; CI runs the scanners in the advisory `scanner-quality` job.
Run `scripts/bootstrap.sh` once to make every default-stage hook runnable.

## Scanners

| Scanner | Version | Scope | Rule |
|---|---|---|---|
| cccc | 1.6.0 | staged package Python | no new or worsened function above cyclomatic 10 or cognitive 15 |
| KISS | 0.4.12 (fleet fork build) | staged package Python | `.config/kiss.toml`, findings attributable to the diff |
| dupehound | 0.1.2 | changed functions | no new function clones |
| jscpd | 5.0.16 | pushed range and full tree | no new copied blocks; census printed |
| scanner census | cccc and KISS | every package module | zero findings, absolutely |

Scanner versions are verified before each run; a missing or different binary
stops the gate rather than passing it. `scripts/install_scanners.sh` is the one
place these versions are installed from, locally and in CI.

## Wiring

| Gate | Fails when |
|---|---|
| orphan modules | a package module is reachable from no public module, entry point or import |
| public API tested | a public name is used by no test |

## Other gates

Secret history, the security and garbage sanitizer, tracked privacy, root
hygiene, `.gitignore` convergence, `uv lock --locked`,
supply-chain pinning, the phase-direction check, stubs, environment reads outside
`config.py`, stdout writes in served code, swallowed errors, import cycles,
event-loop blocking, ruff, mypy (strict), bandit, codespell, vulture, the test
suite, the strict site build, and the wheel build. No gate depends on an
external service such as a vulnerability database.

The `public-surface` gate validates the README badge set, required public
headings, Pages link, local links, document size, current-state language, and the
durable `AGENTS.md` structure. Its repository identity is configured in
`[tool.pipelines_hooks.public_surface]`.

No graph-boundary stub is allowed. SourceIngest, ConnectorPack, and WriteBack
must use epistemic-graph's generated contracts and clients, and readiness must
fail closed when required verified authority has not been injected.
