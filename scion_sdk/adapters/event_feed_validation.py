"""Construction-time validation for the event-feed adapter."""

from __future__ import annotations

from scion_sdk.manifest.presets import ToolPreset

#: Preset fields this adapter does not implement; a configured value is refused
#: at construction rather than silently ignored.
_UNSUPPORTED_PRESET_FIELDS = (
    "checkpoint_path",
    "relationships_path",
    "reconcile_path",
    "authoritative_path",
    "withdrawals_path",
)


def _require_identity(
    connector: str, tool_schema_sha256: str, mapping_reference: str
) -> None:
    if not all((connector, tool_schema_sha256, mapping_reference)):
        raise ValueError(
            "connector, mapping_reference and a pinned tool_schema_sha256 are required"
        )


def _reject_unsupported_preset_fields(preset: ToolPreset) -> None:
    configured = [name for name in _UNSUPPORTED_PRESET_FIELDS if getattr(preset, name)]
    if configured:
        raise ValueError(
            f"preset {preset.name!r}: event feeds do not support {', '.join(configured)}"
        )


def _require_expected_tenant(value: str | None) -> None:
    if value is not None and (
        not isinstance(value, str) or not value or value != value.strip()
    ):
        raise ValueError("expected tenant must be a nonblank exact identity")
