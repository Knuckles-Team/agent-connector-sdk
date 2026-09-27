"""Fail closed unless SDK Release runs against the published EG 2.27 wheel."""

from __future__ import annotations

import json
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "epistemic-graph"
VERSION = "2.27.0"
REQUIREMENT = "epistemic-graph>=2.27.0,<3"
REGISTRY = "https://pypi.org/simple"
ERROR_CATALOG = "epistemic_graph/contract/errors.json"
REQUIRED_AUTH_CODES = {
    "AUTH_TENANT_MISMATCH",
    "AUTH_AUDIENCE_MISMATCH",
    "AUTH_POLICY_VERSION_MISMATCH",
}


def require_lock_contract(project: dict[str, object], lock: dict[str, object]) -> None:
    """Require the exact release floor and one hash-bound registry wheel."""

    dependencies = project.get("project", {}).get("dependencies", [])
    if REQUIREMENT not in dependencies:
        raise ValueError("SDK project must require the published EG 2.27 floor")

    packages = lock.get("package", [])
    roots = [item for item in packages if item.get("name") == "agent-connector-sdk"]
    eg = [item for item in packages if item.get("name") == PACKAGE]
    if len(roots) != 1 or len(eg) != 1:
        raise ValueError("lock must contain one SDK root and one EG distribution")
    _require_root_requirement(roots[0])
    _require_registry_wheels(eg[0])


def _require_root_requirement(root: dict[str, object]) -> None:
    root_reqs = root.get("metadata", {}).get("requires-dist", [])
    if not any(
        req.get("name") == PACKAGE and req.get("specifier") == ">=2.27.0,<3"
        for req in root_reqs
    ):
        raise ValueError("SDK lock root still has a stale EG requirement")


def _require_registry_wheels(package: dict[str, object]) -> None:
    if package.get("version") != VERSION or package.get("source") != {
        "registry": REGISTRY
    }:
        raise ValueError("EG lock must resolve the published 2.27.0 registry release")
    wheels = package.get("wheels", [])
    if not wheels or any(
        not wheel.get("url", "").startswith("https://files.pythonhosted.org/")
        or not wheel.get("hash", "").startswith("sha256:")
        for wheel in wheels
    ):
        raise ValueError("EG lock has no hash-bound published wheel")


def require_installed_contract() -> None:
    """Inspect the interpreter's installed wheel, without an EG source overlay."""

    distribution = metadata.distribution(PACKAGE)
    if distribution.version != VERSION:
        raise ValueError("installed EG version differs from the locked release")
    installed = _require_installed_catalog(distribution)
    _require_engine_and_client(installed)


def _require_installed_catalog(distribution: metadata.Distribution) -> Path:
    installed = Path(distribution.locate_file("")).resolve()
    environment = Path(sys.prefix).resolve()
    if not installed.is_relative_to(environment):
        raise ValueError("EG is not installed in the active SDK environment")
    if distribution.read_text("direct_url.json") is not None:
        raise ValueError("EG came from a direct/local source instead of the registry")
    if distribution.files is None or not any(
        str(file) == ERROR_CATALOG for file in distribution.files
    ):
        raise ValueError("published EG wheel omits its error catalog")
    catalog_path = Path(distribution.locate_file(ERROR_CATALOG)).resolve()
    if not catalog_path.is_relative_to(installed):
        raise ValueError("EG error catalog resolved outside the installed wheel")
    require_error_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
    return installed


def _require_engine_and_client(installed: Path) -> None:
    import epistemic_graph.client as client
    import epistemic_graph.generated.index_repository as generated
    from epistemic_graph import numeric
    from epistemic_graph.engine import __engine__

    if __engine__ != "eg-pyengine" or numeric is None:
        raise ValueError("published EG wheel lacks its folded native kernels")
    for module in (client, generated):
        if not Path(module.__file__).resolve().is_relative_to(installed):
            raise ValueError("EG generated client resolved outside the installed wheel")
    if "file_outcomes" not in generated.IndexResult.model_fields:
        raise ValueError("published EG IndexResult lacks typed file outcomes")
    annotation = client.GraphOperationsClient.index_repository.__annotations__.get(
        "return"
    )
    if "IndexResult" not in str(annotation):
        raise ValueError("published EG IndexRepository return is not typed")


def require_error_catalog(catalog: dict[str, object]) -> None:
    """Require the shipped engine code registry used by downstream clients."""

    if catalog.get("contract_version") != 1:
        raise ValueError("published EG error catalog has an unknown contract version")
    rows = catalog.get("errors")
    if not isinstance(rows, list) or not rows:
        raise ValueError("published EG error catalog is empty")
    codes: set[str] = set()
    auth_codes: set[str] = set()
    for row in rows:
        code, is_auth = _validate_error_row(row)
        if not isinstance(code, str) or not code or code in codes:
            raise ValueError("published EG error catalog has duplicate/invalid codes")
        codes.add(code)
        if is_auth:
            auth_codes.add(code)
    if not REQUIRED_AUTH_CODES.issubset(auth_codes):
        raise ValueError("published EG error catalog lacks auth boundary codes")


def _validate_error_row(row: object) -> tuple[str, bool]:
    if not isinstance(row, dict) or set(row) != {
        "code",
        "class",
        "retryable",
        "http_status_hint",
    }:
        raise ValueError("published EG error catalog has an invalid row")
    code = row["code"]
    if not isinstance(row["class"], str) or not row["class"]:
        raise ValueError("published EG error catalog has an invalid class")
    if not isinstance(row["retryable"], bool):
        raise ValueError("published EG error catalog has an invalid retry flag")
    status = _require_http_hint(row["http_status_hint"])
    return code, row["class"] == "auth" and status == 403 and not row["retryable"]


def _require_http_hint(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 300 <= value < 600:
        raise ValueError("published EG error catalog has an invalid HTTP hint")
    return value


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    require_lock_contract(project, lock)
    require_installed_contract()
    print(
        json.dumps(
            {"distribution": PACKAGE, "version": VERSION, "boundary": "registry-wheel"}
        )
    )


if __name__ == "__main__":
    main()
