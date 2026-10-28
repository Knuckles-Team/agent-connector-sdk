"""Closed failures for governed paper document transfers."""


class DocumentRefusal(RuntimeError):
    """A closed document-transfer refusal without source secrets."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _DocumentRateLimit(DocumentRefusal):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate_limited")
        self.retry_after = retry_after
