"""Errors the connector-sync runner raises."""

from __future__ import annotations

from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.schema_drift import SchemaDriftReport

__all__ = [
    "CredentialResolutionError",
    "RunnerConfigurationError",
    "SchemaDriftQuarantined",
    "SinkReceiptError",
    "StreamPaused",
]


class RunnerConfigurationError(ValueError):
    """The runner configuration or a connector package is unusable.

    Messages name fields, never their values.
    """


class CredentialResolutionError(PermissionError):
    """A connector's credential reference could not be resolved; no session opens."""


class SinkReceiptError(RuntimeError):
    """A sink receipt does not acknowledge exactly what was submitted."""


class SchemaDriftQuarantined(SourceContractError):
    """A page needs review; the source retains it behind the durable checkpoint."""

    def __init__(self, report: SchemaDriftReport) -> None:
        self.report = report
        reasons = ",".join(report.reason_codes)
        super().__init__(
            f"source page quarantined: {report.classification.value}; {reasons}"
        )


class StreamPaused(SourceContractError):
    """A proposed schema repair is unresolved; the sync loop takes no action.

    Raised before any page is extracted or submitted (SDK-SOURCE-INGEST-R003):
    pausing never constructs a candidate schema, validates instances, performs
    a shadow ingest, or activates a repair.
    """

    def __init__(self, source: str, stream: str) -> None:
        self.source = source
        self.stream = stream
        super().__init__(
            f"stream {stream!r} of {source!r} is paused on an unresolved "
            "repair proposal"
        )
