"""Errors the connector-sync runner raises."""

from __future__ import annotations

from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.schema_drift import SchemaDriftReport

__all__ = [
    "CredentialResolutionError",
    "RunnerConfigurationError",
    "SchemaDriftQuarantined",
    "SinkReceiptError",
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
