#!/usr/bin/env python3
"""Reproduce CI's lock-resolved import graph with explicit source provenance.

The pinned EG source checkout supplies generated Python contracts, while this
repository intentionally skips installing its Rust-backed wheel. The graph
therefore records EG's version and direct requirements from that exact source
checkout and uv.lock; every other node (and EG itself when installed) is
verified from real distribution metadata. No synthetic dist-info is created.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "pinned_import_graph.txt"
PROVENANCE_FIXTURE = ROOT / "tests" / "fixtures" / "pinned_import_graph.provenance.json"
LOCK_FILE = ROOT / "uv.lock"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
SOURCE_ROOT = ROOT / ".ci" / "epistemic-graph"
ROOT_DISTRIBUTION = "agent-connector-sdk"
SOURCE_DISTRIBUTION = "epistemic-graph"
SOURCE_REMOTE = "https://github.com/Knuckles-Team/epistemic-graph.git"
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
class SourceDeclaration:
    name: str
    version: str
    revision: str
    remote: str
    import_origin: str
    metadata_sha256: Mapping[str, str]
    declared_dependencies: tuple[str, ...]
    locked_dependencies: tuple[str, ...]
    consumed_modules: Mapping[str, str]

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "git_revision": self.revision,
            "git_remote": self.remote,
            "checkout": ".ci/epistemic-graph",
            "import_origin": self.import_origin,
            "metadata_sha256": dict(sorted(self.metadata_sha256.items())),
            "declared_dependencies": list(self.declared_dependencies),
            "locked_dependencies": list(self.locked_dependencies),
            "consumed_modules": dict(sorted(self.consumed_modules.items())),
            "evidence_kind": "pinned-source-project-metadata",
        }


@dataclass(frozen=True)
class ImportGraphEvidence:
    graph: tuple[str, ...]
    installed_distributions: tuple[str, ...]
    source_declarations: tuple[SourceDeclaration, ...]


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


def _git(source_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        _raise(f"cannot verify pinned EG source checkout with git {args!r}: {exc}")
    return result.stdout.strip()


def _normalize_remote(value: str) -> str:
    if value == "git@github.com:Knuckles-Team/epistemic-graph.git":
        return SOURCE_REMOTE
    return value.rstrip("/")


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


def _metadata_matches(
    left: tuple[str, ...], right: tuple[str, ...], environment: Mapping[str, str]
) -> bool:
    left_keys = {
        _requirement_key(raw)
        for raw in left
        if _active(Requirement(raw), environment, {""})
    }
    right_keys = {
        _requirement_key(raw)
        for raw in right
        if _active(Requirement(raw), environment, {""})
    }
    return left_keys == right_keys


def _source_revision_from_lock(package: LockedPackage) -> str:
    git_url = package.source.get("git")
    if not git_url:
        _raise("uv.lock does not pin epistemic-graph to a Git source")
    parsed = urlsplit(git_url.split("#", 1)[0])
    remote = _normalize_remote(parsed._replace(query="", fragment="").geturl())
    query = parse_qs(parsed.query)
    revision = query.get("rev", [""])[0]
    fragment = git_url.rsplit("#", 1)[-1] if "#" in git_url else ""
    if remote != SOURCE_REMOTE or not re.fullmatch(r"[0-9a-f]{40}", revision):
        _raise(f"uv.lock has an unsupported epistemic-graph source: {git_url}")
    if fragment != revision:
        _raise("uv.lock Git revision and resolved commit differ for epistemic-graph")
    return revision


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


def _verify_import_origins(
    source_root: Path,
    installed: metadata.Distribution | None,
) -> tuple[Path, Mapping[str, str]]:
    source_package = (source_root / "epistemic_graph").resolve()
    try:
        package = importlib.import_module("epistemic_graph")
    except Exception as exc:
        _raise(f"cannot import the pinned epistemic_graph contract source: {exc}")
    package_file = Path(str(getattr(package, "__file__", ""))).resolve()
    if package_file != (source_package / "__init__.py").resolve():
        _raise(
            "epistemic_graph package origin is not the pinned source checkout: "
            f"{package_file}"
        )

    package_paths = {
        Path(str(path)).resolve() for path in getattr(package, "__path__", ())
    }
    allowed_paths = {source_package}
    if installed is not None:
        installed_package = Path(
            str(installed.locate_file("epistemic_graph"))
        ).resolve()
        if installed_package != source_package:
            _raise(
                "installed EG package overlay has no build receipt binding its code "
                "to the pinned source revision"
            )
    if package_paths != allowed_paths:
        _raise(
            "epistemic_graph exposes an unverified package overlay: "
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
        if not origin.is_relative_to(source_package):
            _raise(
                f"SDK-consumed module {module_name} resolves outside the pinned "
                f"source checkout: {origin}"
            )
        origins[module_name] = origin.relative_to(ROOT).as_posix()
    return package_file, origins


def _prove_source_declaration(
    *,
    name: str,
    source_version: str,
    source_requires_python: str,
    source_requires: tuple[str, ...],
    lock_package: LockedPackage,
    lock_metadata: Mapping[str, object],
    lock_source_url: str,
    configured_revision: str,
    bootstrap_revision: str,
    git_revision: str,
    git_remote: str,
    import_origin: Path,
    expected_import_origin: Path,
    environment: Mapping[str, str],
    lock_packages: list[Mapping[str, object]],
) -> tuple[str, ...]:
    if _canonical(name) != SOURCE_DISTRIBUTION:
        _raise(f"pinned source project has unexpected name {name!r}")
    revision = _source_revision_from_lock(lock_package)
    if git_revision != revision:
        _raise(f"EG checkout is {git_revision}, but uv.lock pins {revision}")
    if configured_revision != revision or bootstrap_revision != revision:
        _raise("EG source pin differs between uv.lock, pyproject.toml, and bootstrap")
    if _normalize_remote(git_remote) != SOURCE_REMOTE:
        _raise(f"EG checkout remote is not the canonical source: {git_remote}")
    if (
        source_version != lock_package.version
        or str(lock_metadata.get("version")) != source_version
    ):
        _raise(
            f"EG source version {source_version} does not match uv.lock metadata "
            f"{lock_package.version}"
        )
    if _canonical(str(lock_metadata.get("name", ""))) != SOURCE_DISTRIBUTION:
        _raise("uv.lock copied dependency metadata for the wrong source package")
    if str(lock_metadata.get("requires-python", "")) != source_requires_python:
        _raise("EG source Requires-Python differs from uv.lock dependency metadata")
    lock_requires = lock_metadata.get("requires-dist", [])
    if not isinstance(lock_requires, list) or not _metadata_matches(
        source_requires, tuple(str(value) for value in lock_requires), environment
    ):
        _raise("EG source dependencies differ from uv.lock copied metadata")
    configured_remote = _normalize_remote(lock_source_url)
    lock_remote = _normalize_remote(
        urlsplit(lock_package.source.get("git", "").split("#", 1)[0])
        ._replace(query="", fragment="")
        .geturl()
    )
    if configured_remote != SOURCE_REMOTE or lock_remote != SOURCE_REMOTE:
        _raise("the project source pin differs from the resolved uv.lock source")
    if import_origin.resolve() != expected_import_origin.resolve():
        _raise(
            "epistemic_graph import origin is not the pinned source package: "
            f"{import_origin}"
        )

    source_requirements = [
        Requirement(raw)
        for raw in source_requires
        if _active(Requirement(raw), environment, {""})
    ]
    source_names = {_canonical(requirement.name) for requirement in source_requirements}
    lock_names = {
        _canonical(str(edge.get("name", "")))
        for edge in lock_package.dependencies
        if _active_lock_edge(edge, environment, {""}) and not edge.get("extra")
    }
    if source_names != lock_names:
        _raise(
            "EG source runtime dependencies differ from its uv.lock package edges: "
            f"source={sorted(source_names)}, lock={sorted(lock_names)}"
        )

    locked_dependencies: list[str] = []
    for requirement in source_requirements:
        dependency = _lock_entry(requirement.name, lock_packages, environment)
        if requirement.specifier and not SpecifierSet(
            str(requirement.specifier)
        ).contains(Version(dependency.version), prereleases=True):
            _raise(
                f"locked {requirement.name}=={dependency.version} does not satisfy "
                f"EG source requirement {requirement}"
            )
        locked_dependencies.append(
            f"{_canonical(requirement.name)}=={dependency.version}"
        )
    return tuple(sorted(locked_dependencies))


def _source_declaration(
    lock_data: Mapping[str, object],
    environment: Mapping[str, str],
    installed: metadata.Distribution | None,
) -> SourceDeclaration:
    packages = _lock_packages(lock_data)
    lock_package = _lock_entry(SOURCE_DISTRIBUTION, packages, environment)
    revision = _source_revision_from_lock(lock_package)
    source_root = SOURCE_ROOT.resolve()
    if not source_root.is_dir():
        _raise(f"pinned EG source checkout is missing: {source_root}")

    git_revision = _git(source_root, "rev-parse", "HEAD")
    if git_revision != revision:
        _raise(f"EG checkout is {git_revision}, but uv.lock pins {revision}")
    if _git(source_root, "status", "--porcelain", "--untracked-files=normal"):
        _raise("pinned EG source checkout has local modifications")
    git_remote = _git(source_root, "remote", "get-url", "origin")

    root_project = _read_toml(ROOT_PYPROJECT)
    uv = root_project.get("tool", {}).get("uv", {})  # type: ignore[union-attr]
    sources = uv.get("sources", {})  # type: ignore[union-attr]
    configured_source = sources.get(SOURCE_DISTRIBUTION, {})  # type: ignore[union-attr]
    configured_revision = str(configured_source.get("rev", ""))  # type: ignore[union-attr]
    lock_source_url = str(configured_source.get("git", ""))  # type: ignore[union-attr]

    bootstrap = ROOT / "scripts" / "bootstrap_epistemic_graph_contract.sh"
    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    match = re.search(r"^revision=([0-9a-f]{40})$", bootstrap_text, re.MULTILINE)
    if match is None:
        _raise("EG bootstrap does not declare one immutable revision")
    bootstrap_revision = match.group(1)

    project = _read_toml(source_root / "pyproject.toml").get("project", {})
    cargo = _read_toml(source_root / "Cargo.toml").get("package", {})
    if not isinstance(project, dict) or not isinstance(cargo, dict):
        _raise("EG source project metadata is malformed")
    name = str(project.get("name", ""))
    version = str(cargo.get("version", ""))
    requires_python = str(project.get("requires-python", ""))
    raw_requires = project.get("dependencies", [])
    if not version or not isinstance(raw_requires, list):
        _raise("EG source does not declare a static Cargo version and dependency list")
    requires = tuple(str(value) for value in raw_requires)

    manifest = lock_data.get("manifest", {})
    manifest_metadata = (
        manifest.get("dependency-metadata", []) if isinstance(manifest, dict) else []
    )
    matches = [
        item
        for item in manifest_metadata
        if isinstance(item, dict)
        and _canonical(str(item.get("name", ""))) == SOURCE_DISTRIBUTION
    ]
    if len(matches) != 1:
        _raise("uv.lock must carry one copied EG source dependency-metadata record")

    tool_metadata = uv.get("dependency-metadata", [])  # type: ignore[union-attr]
    tool_matches = [
        item
        for item in tool_metadata
        if isinstance(item, dict)
        and _canonical(str(item.get("name", ""))) == SOURCE_DISTRIBUTION
    ]
    if len(tool_matches) != 1:
        _raise(
            "pyproject.toml must carry one copied EG source dependency-metadata record"
        )
    lock_metadata = matches[0]
    if (
        str(lock_metadata.get("version", "")) != str(tool_matches[0].get("version", ""))
        or str(lock_metadata.get("requires-python", ""))
        != str(tool_matches[0].get("requires-python", ""))
        or not _metadata_matches(
            requires,
            tuple(str(value) for value in lock_metadata.get("requires-dist", [])),
            environment,
        )
        or not _metadata_matches(
            requires,
            tuple(str(value) for value in tool_matches[0].get("requires-dist", [])),
            environment,
        )
    ):
        _raise("copied EG metadata in pyproject.toml and uv.lock differs from source")

    package_file, consumed_modules = _verify_import_origins(source_root, installed)
    locked_dependencies = _prove_source_declaration(
        name=name,
        source_version=version,
        source_requires_python=requires_python,
        source_requires=requires,
        lock_package=lock_package,
        lock_metadata=lock_metadata,
        lock_source_url=lock_source_url,
        configured_revision=configured_revision,
        bootstrap_revision=bootstrap_revision,
        git_revision=git_revision,
        git_remote=git_remote,
        import_origin=package_file,
        expected_import_origin=source_root / "epistemic_graph" / "__init__.py",
        environment=environment,
        lock_packages=packages,
    )
    return SourceDeclaration(
        name=SOURCE_DISTRIBUTION,
        version=version,
        revision=revision,
        remote=SOURCE_REMOTE,
        import_origin=package_file.relative_to(ROOT).as_posix(),
        metadata_sha256={
            "Cargo.toml": hashlib.sha256(
                (source_root / "Cargo.toml").read_bytes()
            ).hexdigest(),
            "pyproject.toml": hashlib.sha256(
                (source_root / "pyproject.toml").read_bytes()
            ).hexdigest(),
        },
        declared_dependencies=tuple(sorted(requires)),
        locked_dependencies=locked_dependencies,
        consumed_modules=consumed_modules,
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
    source_fallback: PackageMetadata,
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
                if key != SOURCE_DISTRIBUTION:
                    _raise(
                        f"required locked runtime dependency {key} has no installed "
                        "distribution metadata"
                    )
                package_metadata = source_fallback
                dist = None
            else:
                package_metadata, dist = result
            lock_package = _lock_entry(key, packages, environment)
            if (
                lock_package.version
                and package_metadata.version != lock_package.version
            ):
                _raise(
                    f"installed/source {key}=={package_metadata.version} differs "
                    f"from uv.lock {lock_package.version}"
                )
            if not lock_package.version and dist is None:
                _raise(
                    "the editable SDK root must have installed distribution metadata"
                )
            if (
                key == SOURCE_DISTRIBUTION
                and package_metadata.version != source_fallback.version
            ):
                _raise(
                    "installed EG version differs from the pinned source declaration"
                )
            cached[key] = (package_metadata, dist)
            graph[key] = f"{key}=={package_metadata.version}"
            if dist is not None:
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


def _validate_installed_source_metadata(
    installed: PackageMetadata,
    source: SourceDeclaration,
    environment: Mapping[str, str],
) -> None:
    if installed.version != source.version:
        _raise("installed EG version differs from the exact pinned source version")
    if not _metadata_matches(
        installed.requires, source.declared_dependencies, environment
    ):
        _raise("installed EG dependency metadata differs from the pinned source")


def compute_import_graph_evidence(
    root: str = ROOT_DISTRIBUTION,
) -> ImportGraphEvidence:
    """Return the lock-verified graph and explicit source/install evidence."""
    lock_data = _read_toml(LOCK_FILE)
    environment = default_environment()
    packages = _lock_packages(lock_data)

    installed_eg = _installed_package(SOURCE_DISTRIBUTION)
    source = _source_declaration(
        lock_data, environment, installed_eg[1] if installed_eg else None
    )
    source_package = PackageMetadata(
        version=source.version,
        requires=source.declared_dependencies,
    )
    if installed_eg is not None:
        _validate_installed_source_metadata(installed_eg[0], source, environment)

    graph, installed = _walk_graph(
        root,
        packages=packages,
        environment=environment,
        get_installed=_installed_package,
        source_fallback=source_package,
    )
    return ImportGraphEvidence(
        graph=graph,
        installed_distributions=installed,
        source_declarations=(source,),
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
        "schema_version": 1,
        "graph_sha256": hashlib.sha256(graph_bytes).hexdigest(),
        "source_declarations": [
            source.to_json() for source in evidence.source_declarations
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
            "after the source proof passes"
        )
    try:
        provenance = json.loads(PROVENANCE_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise(f"cannot read import-graph provenance: {exc}")
    if not isinstance(provenance, dict) or provenance.get("schema_version") != 1:
        _raise("import-graph provenance has an unsupported schema")
    if provenance.get("graph_sha256") != hashlib.sha256(graph_bytes).hexdigest():
        _raise("import-graph provenance digest does not bind the committed graph")
    recorded_sources = provenance.get("source_declarations")
    expected_sources = [source.to_json() for source in evidence.source_declarations]
    if recorded_sources != expected_sources:
        _raise("recorded source-declaration evidence differs from the pinned checkout")
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
            f"{len(evidence.source_declarations)} source declaration(s), "
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
        f"{len(evidence.source_declarations)} source declaration(s), "
        f"{len(evidence.installed_distributions)} installed distribution(s) verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
