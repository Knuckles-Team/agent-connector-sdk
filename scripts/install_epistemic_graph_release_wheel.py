#!/usr/bin/env python3
"""Install the reviewed EG release wheel without building native code."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import urllib.request
from importlib import metadata
from pathlib import Path

from epistemic_graph_wheel_provenance import (
    ProvenanceError,
    read_manifest,
    verify_installed_distribution,
    verify_wheel_archive,
)

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "epistemic_graph_release.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    manifest = read_manifest(MANIFEST)
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache = cache / "agent-connector-sdk" / manifest["wheel_filename"]
    wheel = args.wheel
    if wheel is None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.is_file():
            _download(cache, manifest["wheel_url"], manifest)
        else:
            try:
                verify_wheel_archive(cache, MANIFEST)
            except ProvenanceError:
                _download(cache, manifest["wheel_url"], manifest)
        wheel = cache
    verify_wheel_archive(wheel, MANIFEST)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--reinstall",
            "--no-deps",
            "--python",
            sys.executable,
            str(wheel),
        ],
        check=True,
    )
    verify_installed_distribution(
        metadata.distribution(manifest["distribution"]), MANIFEST
    )
    return 0


def _download(destination: Path, url: str, manifest: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix="eg-wheel-"
    ) as temp:
        wheel = Path(temp) / manifest["wheel_filename"]
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "agent-connector-sdk-bootstrap",
            },
        )
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            wheel.open("wb") as out,
        ):
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        verify_wheel_archive(wheel, MANIFEST)
        wheel.replace(destination)


if __name__ == "__main__":
    raise SystemExit(main())
