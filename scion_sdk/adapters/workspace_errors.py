"""Typed workspace parsing refusals."""

from scion_sdk.adapters.workspace_models import WorkspaceReason


class WorkspaceParseError(ValueError):
    """A parser refusal without file content or path in its message."""

    def __init__(self, reason: WorkspaceReason) -> None:
        self.reason = reason
        super().__init__(reason)
