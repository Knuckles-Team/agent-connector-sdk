"""The configuration-file connector registry."""

from __future__ import annotations

from pathlib import Path

import anyio
import yaml
from pydantic import ValidationError

from agent_connector_sdk.runner.descriptors import ConnectorDescriptor, RunnerConfig
from agent_connector_sdk.runner.errors import RunnerConfigurationError

__all__ = ["StaticConfigRegistry", "load_runner_config"]

_MAX_CONFIG_BYTES = 1024 * 1024


def _field_errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'document'}: {error['msg']}"
        for error in exc.errors()
    )


def load_runner_config(path: Path) -> RunnerConfig:
    """Read and validate a YAML or JSON runner configuration.

    Raises:
        RunnerConfigurationError: the file is unreadable, too large, not YAML,
            or invalid. The message names fields and never their values.
    """
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RunnerConfigurationError(f"{path.name} is unreadable") from exc
    if len(payload) > _MAX_CONFIG_BYTES:
        raise RunnerConfigurationError(f"{path.name} is too large")
    try:
        document = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise RunnerConfigurationError(f"{path.name} is not valid YAML") from exc
    base_dir = path.resolve().parent
    try:
        return RunnerConfig.model_validate(document, context={"base_dir": base_dir})
    except ValidationError as exc:
        # The validation error carries input values, which may be literal
        # secrets; only field locations and messages leave this function.
        raise RunnerConfigurationError(
            f"{path.name} is invalid: {_field_errors(exc)}"
        ) from None


class StaticConfigRegistry:
    """Lists the connectors of a configuration file, re-read on every call."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def connectors(self) -> tuple[ConnectorDescriptor, ...]:
        """The configured connectors."""
        config = await anyio.to_thread.run_sync(load_runner_config, self._path)
        return config.connectors
