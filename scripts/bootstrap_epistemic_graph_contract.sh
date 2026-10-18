#!/usr/bin/env bash
# Prove the SDK reads epistemic-graph's generated contracts from the PyPI wheel
# that uv.lock pins. There is no source checkout and no PYTHONPATH overlay: the
# installed distribution must be the locked registry version, and the contract
# package must resolve only inside that distribution.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run --frozen --no-sync python - <<'PY'
import tomllib
from importlib import metadata
from pathlib import Path

import epistemic_graph
import epistemic_graph.generated.source_ingestion as source

lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
(locked,) = [p for p in lock["package"] if p["name"] == "epistemic-graph"]
if not str(locked.get("source", {}).get("registry", "")).startswith("https://pypi.org/"):
    raise SystemExit(f"uv.lock does not pin epistemic-graph to PyPI: {locked.get('source')}")
# A release may publish an sdist beside its wheels; uv records both. The
# contract is that a published wheel exists and is what installs:
# [tool.uv] no-build-package forbids building epistemic-graph from source.
if not locked.get("wheels"):
    raise SystemExit("uv.lock pins no published epistemic-graph wheel")
dist = metadata.distribution("epistemic-graph")
if dist.version != locked["version"]:
    raise SystemExit(f"installed epistemic-graph {dist.version} != uv.lock {locked['version']}")
package = Path(str(dist.locate_file("epistemic_graph"))).resolve()
paths = {Path(p).resolve() for p in epistemic_graph.__path__}
if paths != {package}:
    raise SystemExit(f"epistemic_graph has a package overlay: {sorted(map(str, paths))}")
if not Path(source.__file__).resolve().is_relative_to(package):
    raise SystemExit(f"generated contract resolves outside the wheel: {source.__file__}")
print(f"epistemic-graph {dist.version} contract: installed PyPI wheel at {package}")
PY
