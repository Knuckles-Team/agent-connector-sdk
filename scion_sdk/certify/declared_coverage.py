"""Typed declared semantic coverage for connector certification.

A connector declares SHACL shapes. This module parses the target classes and
property paths once and refuses shapes that do not cover every declared record
type and the required provenance paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME = r"([A-Za-z_][A-Za-z0-9_-]{0,127})"
_TARGET_CLASS_RE = re.compile(rf"\bsh:targetClass\s+:{_NAME}\b")
_PATH_RE = re.compile(rf"\bsh:path\s+:{_NAME}\b")

REQUIRED_PROVENANCE_PATHS = frozenset(
    {
        "sourceRecordRef",
        "tenantReference",
        "accessPolicyReference",
        "provenanceReference",
    }
)


class DeclaredSemanticCoverageError(RuntimeError):
    """Declared shapes miss a declared record type or a provenance path."""


@dataclass(frozen=True)
class DeclaredSemanticCoverage:
    target_classes: frozenset[str]
    paths: frozenset[str]

    @classmethod
    def from_shapes_text(cls, shapes_text: str) -> DeclaredSemanticCoverage:
        return cls(
            target_classes=frozenset(_TARGET_CLASS_RE.findall(shapes_text)),
            paths=frozenset(_PATH_RE.findall(shapes_text)),
        )

    def require_covers(self, declared_record_types: frozenset[str]) -> None:
        if not (
            declared_record_types <= self.target_classes
            and self.paths >= REQUIRED_PROVENANCE_PATHS
        ):
            raise DeclaredSemanticCoverageError(
                "declared semantic coverage is incomplete"
            )
