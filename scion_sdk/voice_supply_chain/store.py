"""Location of the voice-model manifest index."""

from __future__ import annotations

from pathlib import Path

from scion_sdk.paths import data_dir


def manifest_index_dir() -> Path:
    """Directory holding one JSON manifest file per acquired asset, keyed by digest."""
    d = data_dir() / "voice-models" / "manifests"
    d.mkdir(parents=True, exist_ok=True)
    return d
