#!/usr/bin/env python3
"""Prove that the retired distribution is a metadata-only forwarder."""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from email.policy import strict
from pathlib import Path


class DistributionError(RuntimeError):
    """The compatibility artifact does not satisfy the forwarding contract."""


def _project(source: Path) -> dict[str, object]:
    try:
        document = tomllib.loads(
            (source / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DistributionError(f"cannot read compatibility metadata: {exc}") from exc
    return document


def _project_table(document: dict[str, object]) -> dict[str, object]:
    project = document.get("project")
    if not isinstance(project, dict):
        raise DistributionError("compatibility pyproject has no [project] table")
    return project


def _require_string(project: dict[str, object], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise DistributionError(f"project.{key} must be a non-empty string")
    return value


def _require_metadata_only(source: Path, root: Path) -> tuple[str, str]:
    alias_project = _project_table(_project(source))
    target_project = _project_table(_project(root))
    alias_name = _require_string(alias_project, "name")
    target_name = _require_string(target_project, "name")
    version = _require_string(alias_project, "version")
    target_version = _require_string(target_project, "version")
    if alias_name != "agent-connector-sdk":
        raise DistributionError(f"unexpected alias name: {alias_name}")
    if target_name != "scion-sdk":
        raise DistributionError(f"unexpected target name: {target_name}")
    if version != target_version:
        raise DistributionError(
            f"version mismatch: alias={version}, target={target_version}"
        )
    if alias_project.get("dependencies") != [f"scion-sdk=={version}"]:
        raise DistributionError(
            "the alias must depend exactly on scion-sdk at its own version"
        )

    alias_extras = alias_project.get("optional-dependencies")
    target_extras = target_project.get("optional-dependencies")
    if not isinstance(alias_extras, dict) or not isinstance(target_extras, dict):
        raise DistributionError("optional dependency tables must be mappings")
    if set(alias_extras) != set(target_extras):
        raise DistributionError("the alias extras must match the target extras exactly")
    for extra in sorted(target_extras):
        if alias_extras[extra] != [f"scion-sdk[{extra}]=={version}"]:
            raise DistributionError(f"extra {extra!r} does not forward to scion-sdk")

    for key in ("scripts", "entry-points"):
        if key in alias_project:
            raise DistributionError(
                f"compatibility project must not declare project.{key}"
            )
    tool = _project(source).get("tool")
    setuptools = tool.get("setuptools") if isinstance(tool, dict) else None
    if not isinstance(setuptools, dict):
        raise DistributionError("compatibility project has malformed [tool.setuptools]")
    if setuptools.get("packages") != [] or setuptools.get("py-modules") != []:
        raise DistributionError(
            "compatibility project must declare empty package surfaces"
        )

    allowed = {Path("pyproject.toml"), Path("README.md")}
    generated_metadata = {
        "PKG-INFO",
        "SOURCES.txt",
        "dependency_links.txt",
        "requires.txt",
        "top_level.txt",
    }
    tracked = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}
    unexpected = {
        path
        for path in tracked
        if path not in allowed
        and not (
            len(path.parts) == 2
            and Path(path.parts[0]).suffix == ".egg-info"
            and path.name in generated_metadata
        )
    }
    if unexpected:
        raise DistributionError(
            "compatibility source contains non-metadata files: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    return alias_name, version


def _wheel_metadata(path: Path, name: str, version: str) -> None:
    expected_dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.namelist()
            if not members or any(
                Path(member).parts[0] != expected_dist_info for member in members
            ):
                raise DistributionError(
                    f"{path.name} contains non-metadata wheel members"
                )
            metadata_name = f"{expected_dist_info}/METADATA"
            message = BytesParser(policy=strict).parsebytes(archive.read(metadata_name))
            if message["Name"] != name or message["Version"] != version:
                raise DistributionError(f"{path.name} has incorrect Name or Version")
            requires = sorted(message.get_all("Requires-Dist", []))
            extras = sorted(message.get_all("Provides-Extra", []))
            expected = [f"scion-sdk=={version}"]
            expected.extend(
                f'scion-sdk[{extra}]=={version}; extra == "{extra}"' for extra in extras
            )
            if requires != sorted(expected):
                raise DistributionError(
                    f"{path.name} has unexpected dependencies: {requires!r}"
                )
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise DistributionError(f"cannot inspect {path.name}: {exc}") from exc


def _sdist_metadata(path: Path, name: str, version: str) -> None:
    normalized_name = name.replace("-", "_")
    root_name = f"{normalized_name}-{version}"
    root_prefix = f"{root_name}/"
    metadata_names = {
        "PKG-INFO",
        "SOURCES.txt",
        "dependency_links.txt",
        "requires.txt",
        "top_level.txt",
    }
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.name.rstrip("/") == root_name:
                    continue
                if not member.name.startswith(root_prefix):
                    raise DistributionError(f"{path.name} has an unexpected sdist root")
                relative = member.name.removeprefix(root_prefix)
                if relative in {"PKG-INFO", "README.md", "pyproject.toml", "setup.cfg"}:
                    continue
                if relative.rstrip("/") == f"{normalized_name}.egg-info":
                    continue
                if (
                    relative.startswith(f"{normalized_name}.egg-info/")
                    and Path(relative).name in metadata_names
                ):
                    continue
                raise DistributionError(
                    f"{path.name} contains non-metadata member {relative!r}"
                )
    except (OSError, tarfile.TarError) as exc:
        raise DistributionError(f"cannot inspect {path.name}: {exc}") from exc


def check(dist_dir: Path, source: Path, root: Path) -> None:
    name, version = _require_metadata_only(source, root)
    normalized_name = name.replace("-", "_")
    wheel = dist_dir / f"{normalized_name}-{version}-py3-none-any.whl"
    sdist = dist_dir / f"{normalized_name}-{version}.tar.gz"
    if not wheel.is_file() or not sdist.is_file():
        raise DistributionError(f"expected exactly {wheel.name} and {sdist.name}")
    if (
        len(list(dist_dir.glob("*.whl"))) != 1
        or len(list(dist_dir.glob("*.tar.gz"))) != 1
    ):
        raise DistributionError(
            "compatibility build must contain one wheel and one sdist"
        )
    _wheel_metadata(wheel, name, version)
    _sdist_metadata(sdist, name, version)
    print(
        f"metadata-only compatibility distribution verified: {wheel.name}, {sdist.name}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        check(args.dist_dir.resolve(), args.source.resolve(), args.root.resolve())
    except DistributionError as exc:
        print(f"compatibility distribution check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
