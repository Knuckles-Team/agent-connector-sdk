"""Connector descriptors and runner settings.

A descriptor names a connector package (its manifest, presets and pinned tool
fingerprints), how its MCP server is reached, which presets run, and which data
resources trigger which presets. Credentials are references only
(``env://NAME`` or ``openbao://mount/path#field``); a literal value is rejected.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agent_connector_sdk.auth.oidc import ClientCredentialsConfig
from agent_connector_sdk.credentials.references import parse_secret_reference

__all__ = ["ConnectorDescriptor", "EndpointSpec", "RunnerConfig", "RunnerSettings"]

_CONNECTOR_NAME = r"^[a-z0-9][a-z0-9._-]{0,127}$"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EndpointSpec(_Strict):
    """Where a connector's MCP server is reached (streamable HTTP or stdio)."""

    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    bearer_token: str = ""
    client_credentials: ClientCredentialsConfig | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _check_endpoint(self) -> EndpointSpec:
        if bool(self.url) == bool(self.command):
            raise ValueError("an endpoint needs exactly one of url or command")
        if self.bearer_token and not self.url:
            raise ValueError("bearer_token applies only to a url endpoint")
        references = [*self.env.values(), self.bearer_token]
        for reference in filter(None, references):
            parse_secret_reference(reference)
        return self

    @model_validator(mode="after")
    def _check_client_credentials(self) -> EndpointSpec:
        if self.client_credentials is None:
            return self
        if not self.url:
            raise ValueError("client_credentials applies only to a url endpoint")
        if self.bearer_token:
            raise ValueError("set at most one of bearer_token and client_credentials")
        return self


class ConnectorDescriptor(_Strict):
    """One connector the runner serves.

    ``package_root`` holds ``connector_manifest.yml``; ``connectors_dir`` holds
    the presets and fingerprints (default ``<package_root>/connectors``).
    Relative paths are resolved against the configuration file's directory.
    ``presets`` empty means every ``sync`` preset of the manifest.
    ``data_resources`` maps a resource URI to the presets synced when the
    server reports that resource updated.
    """

    connector: str = Field(pattern=_CONNECTOR_NAME)
    package_root: Path
    connectors_dir: Path | None = None
    endpoint: EndpointSpec
    presets: tuple[str, ...] = ()
    provision: bool = True
    interval_seconds: float = Field(default=900.0, gt=0)
    data_resources: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    mapping_reference: str = ""
    max_pages_per_cycle: int = Field(default=1_000, ge=1, le=1_000_000)

    @field_validator("package_root", "connectors_dir")
    @classmethod
    def _anchor_path(cls, value: Path | None, info: ValidationInfo) -> Path | None:
        base = (info.context or {}).get("base_dir")
        if value is None or value.is_absolute() or base is None:
            return value
        return Path(base) / value

    @property
    def resolved_connectors_dir(self) -> Path:
        """``connectors_dir``, or ``<package_root>/connectors`` when unset."""
        return self.connectors_dir or self.package_root / "connectors"

    @property
    def resolved_mapping_reference(self) -> str:
        """Configured exact mapping, or the single-mapping manifest shorthand."""
        return self.mapping_reference or f"manifest:{self.connector}"


class RunnerSettings(_Strict):
    """Scheduler-wide limits."""

    max_concurrency: int = Field(default=4, ge=1, le=256)
    backoff_initial_seconds: float = Field(default=5.0, gt=0)
    backoff_max_seconds: float = Field(default=600.0, gt=0)
    registry_refresh_seconds: float = Field(default=60.0, gt=0)


class RunnerConfig(_Strict):
    """The ``connector-sync`` configuration document."""

    settings: RunnerSettings = Field(default_factory=RunnerSettings)
    connectors: tuple[ConnectorDescriptor, ...] = ()

    @model_validator(mode="after")
    def _unique_connectors(self) -> RunnerConfig:
        names = [descriptor.connector for descriptor in self.connectors]
        if len(names) != len(set(names)):
            raise ValueError("a connector is declared more than once")
        return self
