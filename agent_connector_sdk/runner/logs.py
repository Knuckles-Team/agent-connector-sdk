"""Structured runner logs.

Every runner log record carries a ``structured`` mapping with an ``event`` name,
the ``connector`` and event fields. The JSON formatter writes one object per
line to stderr; the text formatter writes the human message.
"""

from __future__ import annotations

import json
import logging
import sys

__all__ = ["RUNNER_LOGGER", "JsonLogFormatter", "configure_logging", "structured"]

#: The parent logger of every runner module.
RUNNER_LOGGER = "agent_connector_sdk.runner"


def structured(event: str, connector: str, **fields: object) -> dict[str, object]:
    """The ``extra`` argument for a structured runner log call."""
    return {"structured": {"event": event, "connector": connector, **fields}}


class JsonLogFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message and fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a JSON line."""
        fields = getattr(record, "structured", {})
        document = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **(fields if isinstance(fields, dict) else {}),
        }
        return json.dumps(document, default=str, sort_keys=True)


def configure_logging(log_format: str) -> logging.Logger:
    """Send runner logs to stderr as ``json`` or ``text``; return the runner logger."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        JsonLogFormatter()
        if log_format == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger = logging.getLogger(RUNNER_LOGGER)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
