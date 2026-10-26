#!/usr/bin/env python3
"""Check fresh and in-place installs of the renamed SDK distributions.

The check uses two isolated virtual environments. The fresh environment
installs both distributions at the target version. The migration environment
installs the old alias first, performs the normal alias upgrade, then applies
the documented Scion payload repair. Every environment must retain the
implementation namespace, package resources, console entry points, and clean
dependency metadata. A missing public artifact or failed assertion is an
error; this check has no skipped path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


class UpgradeCheckError(RuntimeError):
    """A compatibility installation or assertion failed."""


_PROBE = textwrap.dedent(
    """
    from __future__ import annotations

    import importlib
    import importlib.metadata as metadata
    import importlib.resources as resources
    import json
    from pathlib import Path
    import sys

    target_version = sys.argv[1]
    target = metadata.distribution("scion-sdk")
    alias = metadata.distribution("agent-connector-sdk")
    assert metadata.version("scion-sdk") == target_version
    assert metadata.version("agent-connector-sdk") == target_version
    package = importlib.import_module("agent_connector_sdk")
    package_root = Path(next(iter(package.__path__))).resolve()
    site_root = Path(next(path for path in sys.path if path.endswith("site-packages"))).resolve()
    assert package_root.is_relative_to(site_root)
    for module in (
        "agent_connector_sdk.connector",
        "agent_connector_sdk.artifacts.pack",
        "agent_connector_sdk.certify.cli",
        "agent_connector_sdk.runner.cli",
    ):
        importlib.import_module(module)
    for resource in (
        "ontology/access_contract.ttl",
        "skills/agent-connector-sdk-development/SKILL.md",
    ):
        assert resources.files("agent_connector_sdk").joinpath(resource).is_file()
    target_files = {str(path) for path in target.files or ()}
    alias_files = {str(path) for path in alias.files or ()}
    owned = {path for path in target_files if path.startswith("agent_connector_sdk/")}
    assert owned
    assert not any(path.startswith("agent_connector_sdk/") for path in alias_files)
    assert not any(path.endswith("entry_points.txt") for path in alias_files)
    entry_points = {
        (entry_point.group, entry_point.name)
        for entry_point in metadata.entry_points()
        if entry_point.dist and entry_point.dist.metadata.get("Name") == "scion-sdk"
    }
    assert ("console_scripts", "connector-sync") in entry_points
    assert ("console_scripts", "connector-certify") in entry_points
    assert (Path(sys.prefix) / "bin" / "connector-sync").is_file()
    assert (Path(sys.prefix) / "bin" / "connector-certify").is_file()
    print(json.dumps({
        "target_version": target_version,
        "package_root": str(package_root),
        "implementation_files_owned_by_scion": len(owned),
        "alias_distribution_files": len(alias_files),
        "entry_points": len(entry_points),
        "resources": [
            "ontology/access_contract.ttl",
            "skills/agent-connector-sdk-development/SKILL.md",
        ],
    }, sort_keys=True))
    """
).strip()


def _python(venv_dir: Path) -> Path:
    """Return the interpreter path for a venv on the current platform."""

    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    path = venv_dir / relative
    if not path.is_file():
        raise UpgradeCheckError(f"virtualenv interpreter is missing: {path}")
    return path


def _source_args(wheelhouse: Path | None) -> list[str]:
    """Return pip source flags, refusing an absent local wheelhouse."""

    if wheelhouse is None:
        return []
    wheelhouse = wheelhouse.resolve()
    if not wheelhouse.is_dir():
        raise UpgradeCheckError(f"wheelhouse is not a directory: {wheelhouse}")
    return ["--no-index", "--find-links", str(wheelhouse)]


def _pip_command(python: Path, *arguments: str) -> list[str]:
    return [str(python), "-m", "pip", "--disable-pip-version-check", *arguments]


def _run(command: list[str], *, cwd: Path, label: str) -> str:
    """Run one isolated command and return its standard output."""

    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        raise UpgradeCheckError(
            f"{label} failed with exit {completed.returncode}:\n{detail}"
        )
    return completed.stdout


def _create_venv(path: Path, *, cwd: Path) -> Path:
    _run([sys.executable, "-m", "venv", str(path)], cwd=cwd, label="create venv")
    return _python(path)


def _probe(python: Path, *, target_version: str, cwd: Path) -> dict[str, object]:
    output = _run([str(python), "-c", _PROBE, target_version], cwd=cwd, label="probe")
    try:
        value = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise UpgradeCheckError(f"probe did not return JSON: {output!r}") from exc
    if not isinstance(value, dict):
        raise UpgradeCheckError("probe returned a non-object result")
    return value


def _pip_check(python: Path, *, cwd: Path) -> str:
    return _run(_pip_command(python, "check"), cwd=cwd, label="pip check").strip()


def _install_fresh(
    python: Path,
    *,
    target_version: str,
    source_args: list[str],
    cwd: Path,
) -> dict[str, object]:
    _run(
        _pip_command(
            python,
            "install",
            *source_args,
            f"scion-sdk=={target_version}",
            f"agent-connector-sdk=={target_version}",
        ),
        cwd=cwd,
        label="fresh install",
    )
    return {
        "probe": _probe(python, target_version=target_version, cwd=cwd),
        "pip_check": _pip_check(python, cwd=cwd),
    }


def _install_migration(
    python: Path,
    *,
    old_version: str,
    target_version: str,
    source_args: list[str],
    cwd: Path,
) -> dict[str, object]:
    _run(
        _pip_command(
            python,
            "install",
            *source_args,
            f"agent-connector-sdk=={old_version}",
        ),
        cwd=cwd,
        label="old distribution install",
    )
    _run(
        _pip_command(
            python,
            "install",
            "--upgrade",
            *source_args,
            f"agent-connector-sdk=={target_version}",
        ),
        cwd=cwd,
        label="in-place alias upgrade",
    )
    _run(
        _pip_command(
            python,
            "install",
            "--force-reinstall",
            "--no-deps",
            *source_args,
            f"scion-sdk=={target_version}",
        ),
        cwd=cwd,
        label="Scion payload repair",
    )
    return {
        "probe": _probe(python, target_version=target_version, cwd=cwd),
        "pip_check": _pip_check(python, cwd=cwd),
    }


def run_check(
    *,
    old_version: str,
    target_version: str,
    wheelhouse: Path | None = None,
    work_dir: Path | None = None,
) -> dict[str, object]:
    """Run both isolated installation paths and return their evidence."""

    source_args = _source_args(wheelhouse)
    parent = work_dir.resolve() if work_dir else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="compatibility-upgrade-", dir=parent
    ) as raw:
        root = Path(raw)
        fresh_python = _create_venv(root / "fresh", cwd=root)
        inplace_python = _create_venv(root / "inplace", cwd=root)
        result: dict[str, object] = {
            "schema": "scion-compatibility-upgrade/v1",
            "old_version": old_version,
            "target_version": target_version,
            "wheelhouse": str(wheelhouse.resolve()) if wheelhouse else None,
            "skipped_checks": 0,
            "fresh": _install_fresh(
                fresh_python,
                target_version=target_version,
                source_args=source_args,
                cwd=root,
            ),
            "inplace_repaired": _install_migration(
                inplace_python,
                old_version=old_version,
                target_version=target_version,
                source_args=source_args,
                cwd=root,
            ),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        help="use only this public-wheel cache instead of the default PyPI index",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="parent for the temporary venvs; it is never treated as a source tree",
    )
    parser.add_argument(
        "--output", type=Path, help="write the JSON evidence to this path"
    )
    args = parser.parse_args(argv)
    try:
        result = run_check(
            old_version=args.old_version,
            target_version=args.target_version,
            wheelhouse=args.wheelhouse,
            work_dir=args.work_dir,
        )
    except UpgradeCheckError as exc:
        print(f"compatibility upgrade check failed: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
