"""Strict, bounded models for the Arrow data-preparation kernel.

The models are deliberately independent of Arrow.  A plan is validated before
an input table is inspected, and its allow-listed verbs are dispatched by the
kernel with explicit ``isinstance`` branches.  ``ProtocolModel`` is the
existing fail-closed protocol base: unknown fields, primitive coercion and
post-construction assignment are rejected.
"""

from __future__ import annotations

from ._types import (
    ArrowTypeName,
    ColumnName,
    Digest,
    InvalidRowDisposition,
    OpaqueReference,
    ProfileScalar,
    ProfileTargetKind,
    ProfileWarningCode,
    ScalarValue,
    SchemaVersion,
)
from .evidence import PrepEvidence, QuarantineOutcome, RowOutcome, StepEvidence
from .plan import (
    STEP_VERBS,
    CanonicalNames,
    CleanPlan,
    CleanStep,
    Dedupe,
    FillNulls,
    LocalProfile,
    NullPolicy,
    SafeCast,
)
from .profile import (
    ColumnProfile,
    ProfileEvidenceReference,
    ProfileLimits,
    ProfileRequest,
    ProfileResult,
    ProfileSelector,
    ProfileTarget,
    QuantilePoint,
    TopKEntry,
)

__all__ = [
    "STEP_VERBS",
    "ArrowTypeName",
    "CanonicalNames",
    "CleanPlan",
    "CleanStep",
    "ColumnName",
    "ColumnProfile",
    "Dedupe",
    "Digest",
    "FillNulls",
    "InvalidRowDisposition",
    "LocalProfile",
    "NullPolicy",
    "OpaqueReference",
    "PrepEvidence",
    "ProfileEvidenceReference",
    "ProfileLimits",
    "ProfileRequest",
    "ProfileResult",
    "ProfileScalar",
    "ProfileSelector",
    "ProfileTarget",
    "ProfileTargetKind",
    "ProfileWarningCode",
    "QuantilePoint",
    "QuarantineOutcome",
    "RowOutcome",
    "SafeCast",
    "ScalarValue",
    "SchemaVersion",
    "StepEvidence",
    "TopKEntry",
]
