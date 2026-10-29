#!/usr/bin/env bash
# Caller setup for the shared main_pipeline.yml jobs (full tests and the Python
# 3.12 backward smoke). Installs the locked test environment on the interpreter
# the job provisioned (setup-uv exports UV_PYTHON; no --python override, so the
# backward job really runs 3.12) and proves the epistemic-graph PyPI-wheel
# contract. The identity catalog and git hooks belong to the gates jobs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv sync --frozen --group test
bash scripts/bootstrap_epistemic_graph_contract.sh
