"""Conformance checks over declared metadata, entry points and ontology."""

from __future__ import annotations

from scion_sdk.config_mounts import ConfigMountError, config_mounts
from scion_sdk.connector import ResolvedConnector
from scion_sdk.testing._conformance_static import (
    REMOVED_PROVIDER_GROUPS,
    ConformanceFailure,
    _require,
    pyproject,
)
from scion_sdk.testing.ontology_rollup import orphan_classes


def _check_ontology_rollup(resolved: ResolvedConnector) -> None:
    """Every ontology class reaches the epistemic-graph core namespace."""
    for path in sorted(resolved.dirs.ontology.glob("*.ttl")):
        orphans = orphan_classes(path)
        _require(not orphans, f"{path.name}: orphan classes {sorted(orphans)}")


def _check_one_entry_point(resolved: ResolvedConnector) -> None:
    """Content is found by convention: no provider entry points are declared."""
    declared = pyproject(resolved).get("project", {}).get("entry-points", {})
    stale = [g for g in REMOVED_PROVIDER_GROUPS if g in declared]
    _require(
        not stale,
        f"remove entry-point groups {stale}; the SDK finds content by convention",
    )


def _check_config_mounts(resolved: ResolvedConnector) -> None:
    """Declared container config mounts follow the SDK schema."""
    try:
        config_mounts(pyproject(resolved))
    except ConfigMountError as exc:
        raise ConformanceFailure(f"config_mounts: {exc}") from exc
