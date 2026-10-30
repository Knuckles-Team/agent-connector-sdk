"""Exact dry-run preview expectations and the observation binding check."""

from __future__ import annotations

import json
from typing import NamedTuple

from epistemic_graph.generated.write_back import SourceChangeSet

from scion_sdk.writeback.errors import ChangeSetValidationError
from scion_sdk.writeback.models import DryRunObservation, SourceSnapshot

__all__ = ["ExpectedPreview", "expected_preview", "require_preview_binding"]


class ExpectedPreview(NamedTuple):
    """Canonical before/after encodings and the fields the patch changes."""

    before: str
    after: str
    changed: set[str]


def _encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def expected_preview(
    change_set: SourceChangeSet, current: SourceSnapshot
) -> ExpectedPreview:
    """Compute what an honest transport preview must report."""
    before = {name: current.fields.get(name) for name in change_set.field_scope}
    after = dict(change_set.desired_patch)
    try:
        changed = {
            name
            for name in change_set.field_scope
            if _encode(before[name]) != _encode(after[name])
        }
        return ExpectedPreview(_encode(before), _encode(after), changed)
    except (TypeError, ValueError):
        raise ChangeSetValidationError("invalid dry-run preview values") from None


def require_preview_binding(
    change_set: SourceChangeSet,
    current: SourceSnapshot,
    expected: ExpectedPreview,
    result: DryRunObservation,
) -> None:
    """Refuse a transport preview that does not match the exact expectation."""
    try:
        matches = (
            _encode(result.before) == expected.before
            and _encode(result.after) == expected.after
        )
    except (TypeError, ValueError):
        raise ChangeSetValidationError("invalid dry-run preview values") from None
    if (
        result.change_set_digest != change_set.change_set_digest
        or result.desired_patch_digest != change_set.patch_digest()
        or change_set.change_set_digest != change_set.canonical_digest()
        or result.source_version != current.source_version
        or not matches
        or len(result.changed_fields) != len(expected.changed)
        or set(result.changed_fields) != expected.changed
    ):
        raise ChangeSetValidationError("dry-run observation binding mismatch")
