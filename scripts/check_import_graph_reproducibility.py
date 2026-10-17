#!/usr/bin/env python3
"""Reproduce CI's lock-resolved import graph with explicit registry provenance.

epistemic-graph installs from PyPI only: uv.lock pins it to registry wheels by
hash (no sdist, and ``[tool.uv] no-build-package`` forbids a source build), and
the SDK's generated-contract imports must resolve inside that installed wheel.
Every node of the graph, EG included, is verified from real installed
distribution metadata against uv.lock. No synthetic dist-info is created.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.util
import json
import re
import sys
import tomllib
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

import epistemic_graph_wheel_provenance as eg_wheel
from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "pinned_import_graph.txt"
PROVENANCE_FIXTURE = ROOT / "tests" / "fixtures" / "pinned_import_graph.provenance.json"
RELEASE_MANIFEST = ROOT / "scripts" / "epistemic_graph_release.json"
LOCK_FILE = ROOT / "uv.lock"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
ROOT_DISTRIBUTION = "agent-connector-sdk"
SOURCE_DISTRIBUTION = "epistemic-graph"
REGISTRY = "https://pypi.org/simple"
EVIDENCE_KIND = "pypi-registry-wheel"
# These imports are deliberately dynamic in DecideTransport._generated.
DYNAMIC_SDK_IMPORTS = (
    "epistemic_graph.generated.query",
    "epistemic_graph.generated.coordination",
)


class ImportGraphError(RuntimeError):
    """A lock, install, or source-contract fact cannot be proven."""


@dataclass(frozen=True)
class LockedPackage:
    version: str
    source: Mapping[str, str]
    dependencies: tuple[Mapping[str, object], ...]
    optional_dependencies: Mapping[str, tuple[Mapping[str, object], ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class PackageMetadata:
    version: str
    requires: tuple[str, ...]


@dataclass(frozen=True)
class RegistryDeclaration:
    """EG as locked from PyPI and as installed from that wheel."""

    name: str
    version: str
    registry: str
    locked_wheels: Mapping[str, str]
    declared_dependencies: tuple[str, ...]
    locked_dependencies: tuple[str, ...]
    consumed_modules: Mapping[str, str]
    release_wheel_filename: str
    release_wheel_sha256: str

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "registry": self.registry,
            "locked_wheels": dict(sorted(self.locked_wheels.items())),
            "declared_dependencies": list(self.declared_dependencies),
            "locked_dependencies": list(self.locked_dependencies),
            "consumed_modules": dict(sorted(self.consumed_modules.items())),
            "release_wheel_filename": self.release_wheel_filename,
            "release_wheel_sha256": self.release_wheel_sha256,
            "evidence_kind": EVIDENCE_KIND,
        }


@dataclass(frozen=True)
class ImportGraphEvidence:
    graph: tuple[str, ...]
    installed_distributions: tuple[str, ...]
    registry_declarations: tuple[RegistryDeclaration, ...]


def _canonical(name: str) -> str:
    return canonicalize_name(name)


def _raise(message: str) -> None:
    raise ImportGraphError(message)


def _read_toml(path: Path) -> dict[str, object]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _raise(f"cannot read TOML metadata at {path}: {exc}")
    return value


def _requirement_key(raw: str) -> tuple[str, tuple[str, ...], str, str, str | None]:
    try:
        requirement = Requirement(raw)
    except Exception as exc:
        _raise(f"invalid dependency declaration {raw!r}: {exc}")
    return (
        _canonical(requirement.name),
        tuple(sorted(_canonical(extra) for extra in requirement.extras)),
        str(SpecifierSet(str(requirement.specifier))),
        str(requirement.marker) if requirement.marker else "",
        requirement.url,
    )


def _active(
    requirement: Requirement, environment: Mapping[str, str], extras: set[str]
) -> bool:
    if requirement.marker is None:
        return True
    contexts = extras or {""}
    return any(
        requirement.marker.evaluate({**environment, "extra": extra})
        for extra in contexts
    )


def _active_lock_edge(
    edge: Mapping[str, object], environment: Mapping[str, str], extras: set[str]
) -> bool:
    marker = edge.get("marker")
    if not isinstance(marker, str):
        return True
    try:
        parsed = Marker(marker)
    except Exception as exc:
        _raise(f"invalid uv.lock dependency marker {marker!r}: {exc}")
    contexts = {"", *extras}
    return any(parsed.evaluate({**environment, "extra": extra}) for extra in contexts)


def _lock_packages(lock_data: Mapping[str, object]) -> list[Mapping[str, object]]:
    packages = lock_data.get("package")
    if not isinstance(packages, list):
        _raise("uv.lock has no package table")
    return [package for package in packages if isinstance(package, dict)]


def _lock_entry(
    name: str,
    packages: list[Mapping[str, object]],
    environment: Mapping[str, str],
) -> LockedPackage:
    candidates: list[Mapping[str, object]] = []
    for package in packages:
        if _canonical(str(package.get("name", ""))) != _canonical(name):
            continue
        markers = package.get("resolution-markers", [])
        if isinstance(markers, list) and markers:
            try:
                if not any(
                    Marker(str(marker)).evaluate(environment) for marker in markers
                ):
                    continue
            except Exception as exc:
                _raise(f"invalid lock resolution marker for {name}: {exc}")
        candidates.append(package)
    if not candidates:
        _raise(f"{name} is required by the runtime graph but absent from uv.lock")

    identities = {
        (
            str(package.get("version", "")),
            json.dumps(package.get("source", {}), sort_keys=True),
        )
        for package in candidates
    }
    if len(identities) != 1:
        _raise(
            f"uv.lock selects ambiguous versions or sources for {name}: {identities}"
        )
    package = candidates[0]
    version = str(package.get("version", ""))
    source = package.get("source", {})
    dependencies = package.get("dependencies", [])
    optional_dependencies = package.get("optional-dependencies", {})
    if (
        not isinstance(source, dict)
        or not isinstance(dependencies, list)
        or not isinstance(optional_dependencies, dict)
    ):
        _raise(f"uv.lock package record is malformed for {name}")
    if not version and not (
        _canonical(name) == ROOT_DISTRIBUTION and source.get("editable") == "."
    ):
        _raise(f"uv.lock has no version for locked dependency {name}")
    return LockedPackage(
        version=version,
        source={str(key): str(value) for key, value in source.items()},
        dependencies=tuple(
            dependency for dependency in dependencies if isinstance(dependency, dict)
        ),
        optional_dependencies={
            str(extra): tuple(
                dependency for dependency in edges if isinstance(dependency, dict)
            )
            for extra, edges in optional_dependencies.items()
            if isinstance(edges, list)
        },
    )


def _package_metadata(dist: metadata.Distribution) -> PackageMetadata:
    return PackageMetadata(
        version=dist.version,
        requires=tuple(dist.requires or ()),
    )


def _requirement_names(
    requirements: tuple[str, ...], environment: Mapping[str, str]
) -> set[str]:
    result = set()
    for raw in requirements:
        try:
            requirement = Requirement(raw)
        except Exception as exc:
            _raise(f"invalid Requires-Dist entry {raw!r}: {exc}")
        if _active(requirement, environment, {""}):
            result.add(_canonical(requirement.name))
    return result


def _find_sdk_imports() -> list[str]:
    modules: set[str] = set()
    package_root = ROOT / "agent_connector_sdk"
    for path in sorted(package_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            _raise(f"cannot inspect SDK imports in {path}: {exc}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(
                    alias.name
                    for alias in node.names
                    if alias.name == SOURCE_DISTRIBUTION.replace("-", "_")
                    or alias.name.startswith("epistemic_graph.")
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (
                    node.module == "epistemic_graph"
                    or node.module.startswith("epistemic_graph.")
                )
            ):
                modules.add(node.module)
    modules.update(DYNAMIC_SDK_IMPORTS)
    modules.add("epistemic_graph")
    return sorted(modules)


def _verify_import_origins(installed: metadata.Distribution) -> Mapping[str, str]:
    """Every SDK-consumed EG module resolves inside the installed wheel only."""
    wheel_package = Path(str(installed.locate_file("epistemic_graph"))).resolve()
    site_root = wheel_package.parent
    try:
        package = importlib.import_module("epistemic_graph")
    except Exception as exc:
        _raise(f"cannot import the installed epistemic_graph wheel: {exc}")
    package_paths = {
        Path(str(path)).resolve() for path in getattr(package, "__path__", ())
    }
    if package_paths != {wheel_package}:
        _raise(
            "epistemic_graph exposes a package overlay beyond the installed wheel: "
            f"{sorted(str(path) for path in package_paths)}"
        )
    origins: dict[str, str] = {}
    for module_name in _find_sdk_imports():
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            _raise(f"cannot resolve SDK-consumed module {module_name}: {exc}")
        if spec is None or spec.origin is None:
            _raise(f"SDK-consumed module has no resolved file origin: {module_name}")
        origin = Path(spec.origin).resolve()
        if not origin.is_relative_to(wheel_package):
            _raise(
                f"SDK-consumed module {module_name} resolves outside the installed "
                f"PyPI wheel: {origin}"
            )
        origins[module_name] = origin.relative_to(site_root).as_posix()
    return origins


def _locked_wheels(package: Mapping[str, object]) -> dict[str, str]:
    """The locked registry wheels of EG, by filename; a source build is refused."""
    source = package.get("source", {})
    registry = source.get("registry") if isinstance(source, dict) else None
    if registry != REGISTRY:
        _raise(f"uv.lock must pin epistemic-graph to {REGISTRY}, not {source}")
    if "sdist" in package:
        _raise("uv.lock must not carry an epistemic-graph sdist (no source build)")
    wheels = package.get("wheels", [])
    found: dict[str, str] = {}
    for wheel in wheels if isinstance(wheels, list) else []:
        url = str(wheel.get("url", "")) if isinstance(wheel, dict) else ""
        digest = str(wheel.get("hash", "")) if isinstance(wheel, dict) else ""
        filename = Path(urlsplit(url).path).name
        if not filename.endswith(".whl") or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", digest
        ):
            _raise(f"uv.lock has an unverifiable epistemic-graph wheel: {wheel}")
        found[filename] = digest.removeprefix("sha256:")
    if not found:
        _raise("uv.lock pins no epistemic-graph wheel")
    return found


def _no_build_configured(pyproject: Mapping[str, object]) -> None:
    uv = pyproject.get("tool", {}).get("uv", {})  # type: ignore[union-attr]
    if SOURCE_DISTRIBUTION not in uv.get("no-build-package", []):  # type: ignore[union-attr]
        _raise("pyproject.toml must list epistemic-graph in [tool.uv] no-build-package")
    if SOURCE_DISTRIBUTION in uv.get("sources", {}):  # type: ignore[union-attr]
        _raise("pyproject.toml must not override the epistemic-graph source")


def _registry_declaration(
    lock_data: Mapping[str, object],
    environment: Mapping[str, str],
    installed: metadata.Distribution | None,
) -> RegistryDeclaration:
    if installed is None:
        _raise("epistemic-graph is not installed; run scripts/bootstrap.sh")
    _no_build_configured(_read_toml(ROOT_PYPROJECT))
    packages = _lock_packages(lock_data)
    (package,) = [
        item
        for item in packages
        if _canonical(str(item.get("name", ""))) == SOURCE_DISTRIBUTION
    ] or [{}]
    wheels = _locked_wheels(package)
    lock_package = _lock_entry(SOURCE_DISTRIBUTION, packages, environment)
    if installed.version != lock_package.version:
        _raise(
            f"installed epistemic-graph {installed.version} differs from uv.lock "
            f"{lock_package.version}"
        )
    manifest = eg_wheel.read_manifest(RELEASE_MANIFEST)
    if manifest["version"] != lock_package.version or (
        wheels.get(manifest["wheel_filename"]) != manifest["wheel_sha256"]
    ):
        _raise(
            "scripts/epistemic_graph_release.json does not name a wheel uv.lock pins"
        )
    declared = tuple(sorted(installed.requires or ()))
    locked = tuple(
        sorted(
            f"{_canonical(r.name)}=="
            + _locked_dependency(r, lock_package, packages, environment, set()).version
            for r in (Requirement(raw) for raw in declared)
            if _active(r, environment, {""})
        )
    )
    return RegistryDeclaration(
        name=SOURCE_DISTRIBUTION,
        version=lock_package.version,
        registry=REGISTRY,
        locked_wheels=wheels,
        declared_dependencies=declared,
        locked_dependencies=locked,
        consumed_modules=_verify_import_origins(installed),
        release_wheel_filename=manifest["wheel_filename"],
        release_wheel_sha256=manifest["wheel_sha256"],
    )


def _installed_package(name: str) -> tuple[PackageMetadata, object] | None:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    return _package_metadata(dist), dist


def _requirements_for_contexts(
    package: PackageMetadata,
    environment: Mapping[str, str],
    extras: set[str],
) -> list[Requirement]:
    contexts = {"", *extras}
    requirements: dict[
        tuple[str, tuple[str, ...], str, str, str | None], Requirement
    ] = {}
    for raw in package.requires:
        try:
            requirement = Requirement(raw)
        except Exception as exc:
            _raise(f"invalid Requires-Dist entry for package: {raw!r}: {exc}")
        if _active(requirement, environment, contexts):
            requirements[_requirement_key(raw)] = requirement
    return list(requirements.values())


def _locked_dependency(
    requirement: Requirement,
    parent: LockedPackage,
    packages: list[Mapping[str, object]],
    environment: Mapping[str, str],
    extras: set[str],
) -> LockedPackage:
    name = _canonical(requirement.name)
    lock_edges = list(parent.dependencies)
    for extra in extras:
        lock_edges.extend(parent.optional_dependencies.get(extra, ()))
    edges = [
        edge
        for edge in lock_edges
        if _canonical(str(edge.get("name", ""))) == name
        and tuple(sorted(_canonical(str(value)) for value in edge.get("extra", [])))
        == tuple(sorted(_canonical(value) for value in requirement.extras))
        and _active_lock_edge(edge, environment, extras)
    ]
    if not edges:
        _raise(
            f"{parent.version} lock record omits active dependency "
            f"{requirement.name}{sorted(requirement.extras)}"
        )
    locked = _lock_entry(name, packages, environment)
    if requirement.specifier and not SpecifierSet(str(requirement.specifier)).contains(
        Version(locked.version), prereleases=True
    ):
        _raise(
            f"locked {name}=={locked.version} does not satisfy "
            f"Requires-Dist {requirement}"
        )
    return locked


def _walk_graph(
    root: str,
    *,
    packages: list[Mapping[str, object]],
    environment: Mapping[str, str],
    get_installed: Callable[[str], tuple[PackageMetadata, object] | None],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    pending: deque[tuple[str, frozenset[str]]] = deque([(root, frozenset())])
    requested_extras: dict[str, set[str]] = {}
    processed_contexts: dict[str, set[str]] = {}
    graph: dict[str, str] = {}
    installed: set[str] = set()
    cached: dict[str, tuple[PackageMetadata, object | None]] = {}

    while pending:
        name, extras = pending.popleft()
        key = _canonical(name)
        accumulated = requested_extras.setdefault(key, set())
        new_extras = {_canonical(extra) for extra in extras} - accumulated
        first_visit = key not in cached
        if not first_visit and not new_extras:
            continue
        accumulated.update(_canonical(extra) for extra in extras)

        if first_visit:
            result = get_installed(key)
            if result is None:
                _raise(
                    f"required locked runtime dependency {key} has no installed "
                    "distribution metadata"
                )
            package_metadata, dist = result
            lock_package = _lock_entry(key, packages, environment)
            if (
                lock_package.version
                and package_metadata.version != lock_package.version
            ):
                _raise(
                    f"installed {key}=={package_metadata.version} differs "
                    f"from uv.lock {lock_package.version}"
                )
            if not lock_package.version and dist is None:
                _raise(
                    "the editable SDK root must have installed distribution metadata"
                )
            cached[key] = (package_metadata, dist)
            graph[key] = f"{key}=={package_metadata.version}"
            installed.add(graph[key])

        package_metadata, _ = cached[key]
        contexts = ({""} if first_visit else set()) | new_extras
        processed = processed_contexts.setdefault(key, set())
        contexts -= processed
        if not contexts:
            continue
        processed.update(contexts)
        parent_lock = _lock_entry(key, packages, environment)
        for requirement in _requirements_for_contexts(
            package_metadata, environment, contexts
        ):
            child_lock = _locked_dependency(
                requirement,
                parent_lock,
                packages,
                environment,
                contexts,
            )
            pending.append(
                (
                    requirement.name,
                    frozenset(_canonical(extra) for extra in requirement.extras),
                )
            )
            if child_lock.version == "":
                _raise(f"uv.lock has no selected version for {requirement.name}")

    return tuple(sorted(graph.values())), tuple(sorted(installed))


def compute_import_graph_evidence(
    root: str = ROOT_DISTRIBUTION,
) -> ImportGraphEvidence:
    """Return the lock-verified graph and explicit registry/install evidence."""
    lock_data = _read_toml(LOCK_FILE)
    environment = default_environment()
    packages = _lock_packages(lock_data)
    installed_eg = _installed_package(SOURCE_DISTRIBUTION)
    declaration = _registry_declaration(
        lock_data, environment, installed_eg[1] if installed_eg else None
    )
    graph, installed = _walk_graph(
        root,
        packages=packages,
        environment=environment,
        get_installed=_installed_package,
    )
    return ImportGraphEvidence(
        graph=graph,
        installed_distributions=installed,
        registry_declarations=(declaration,),
    )


def compute_import_graph(root: str = ROOT_DISTRIBUTION) -> list[str]:
    """Return the sorted lock-checked name==version runtime dependency closure."""
    return list(compute_import_graph_evidence(root).graph)


def read_recorded_graph(fixture: Path = FIXTURE) -> list[str]:
    return [line for line in fixture.read_text(encoding="utf-8").splitlines() if line]


def _graph_bytes(graph: tuple[str, ...] | list[str]) -> bytes:
    return ("\n".join(graph) + "\n").encode("utf-8")


def _write_recording(evidence: ImportGraphEvidence) -> None:
    graph_bytes = _graph_bytes(evidence.graph)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(graph_bytes)
    provenance = {
        "schema_version": 2,
        "graph_sha256": hashlib.sha256(graph_bytes).hexdigest(),
        "registry_declarations": [
            declaration.to_json() for declaration in evidence.registry_declarations
        ],
        "installed_distributions": list(evidence.installed_distributions),
        "installed_evidence_kind": "importlib.metadata distribution metadata",
    }
    PROVENANCE_FIXTURE.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_recorded_provenance(
    evidence: ImportGraphEvidence, graph_bytes: bytes
) -> None:
    if not PROVENANCE_FIXTURE.exists():
        _raise(
            f"missing provenance record at {PROVENANCE_FIXTURE}; run --record "
            "after the registry proof passes"
        )
    try:
        provenance = json.loads(PROVENANCE_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise(f"cannot read import-graph provenance: {exc}")
    if not isinstance(provenance, dict) or provenance.get("schema_version") != 2:
        _raise("import-graph provenance has an unsupported schema")
    if provenance.get("graph_sha256") != hashlib.sha256(graph_bytes).hexdigest():
        _raise("import-graph provenance digest does not bind the committed graph")
    recorded = provenance.get("registry_declarations")
    expected = [item.to_json() for item in evidence.registry_declarations]
    if recorded != expected:
        _raise(
            "recorded registry-declaration evidence differs from the installed wheel"
        )
    installed = provenance.get("installed_distributions")
    if (
        not isinstance(installed, list)
        or not all(isinstance(item, str) and "==" in item for item in installed)
        or installed != sorted(set(installed))
    ):
        _raise("provenance does not contain canonical installed distribution evidence")
    if tuple(installed) != evidence.installed_distributions:
        _raise("recorded installed-distribution evidence differs from live metadata")
    if provenance.get("installed_evidence_kind") != (
        "importlib.metadata distribution metadata"
    ):
        _raise("recorded installed-distribution evidence kind is unsupported")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="rewrite the graph and provenance only after every proof succeeds",
    )
    args = parser.parse_args(argv)

    try:
        evidence = compute_import_graph_evidence()
    except ImportGraphError as exc:
        print(f"check_import_graph_reproducibility: CANNOT RUN: {exc}", file=sys.stderr)
        return 2

    graph_bytes = _graph_bytes(evidence.graph)
    if args.record:
        _write_recording(evidence)
        print(
            "check_import_graph_reproducibility: recorded "
            f"{len(evidence.graph)} packages; "
            f"{len(evidence.registry_declarations)} registry declaration(s), "
            f"{len(evidence.installed_distributions)} installed distribution(s)"
        )
        return 0

    if not FIXTURE.exists():
        print(
            f"check_import_graph_reproducibility: CANNOT RUN: no recorded graph at {FIXTURE}; run with --record first",
            file=sys.stderr,
        )
        return 2
    try:
        _validate_recorded_provenance(evidence, graph_bytes)
    except ImportGraphError as exc:
        print(f"check_import_graph_reproducibility: CANNOT RUN: {exc}", file=sys.stderr)
        return 2

    recorded = read_recorded_graph()
    live = list(evidence.graph)
    if live != recorded:
        only_local = sorted(set(live) - set(recorded))
        only_recorded = sorted(set(recorded) - set(live))
        print(
            "check_import_graph_reproducibility: import graph drifted from the recorded hosted result",
            file=sys.stderr,
        )
        if only_local:
            print(f"  only in the local resolve: {only_local}", file=sys.stderr)
        if only_recorded:
            print(f"  only in the recorded result: {only_recorded}", file=sys.stderr)
        return 1

    print(
        f"check_import_graph_reproducibility: {len(live)} packages match; "
        f"{len(evidence.registry_declarations)} registry declaration(s), "
        f"{len(evidence.installed_distributions)} installed distribution(s) verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
