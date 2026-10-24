"""Declared configuration mounts of a connector container (SDK-CONNECTOR-CONTROL-R019.3).

A connector that reads a reference-only configuration directory at run time
declares the mount once, in ``pyproject.toml``, where the shared container
renderer reads it::

    [[tool.pipelines.container.config_mounts]]
    source = "${CONNECTOR_CONFIG_DIR:?set-CONNECTOR_CONFIG_DIR}"
    target = "/etc/connector"

``source`` is a host path or a compose interpolation of one; ``target`` is the
absolute container directory under ``/etc``. Every config mount is a read-only bind
mount. This module owns the field's schema (:data:`CONFIG_MOUNTS_SCHEMA`) and
its validation (:func:`config_mounts`); the conformance plugin runs it for every
connector repository.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

__all__ = [
    "CONFIG_MOUNTS_SCHEMA",
    "CONFIG_ROOT",
    "ConfigMount",
    "ConfigMountError",
    "config_mounts",
]

#: The container directory every config mount sits under.
CONFIG_ROOT: Final = PurePosixPath("/etc")
_INTERPOLATION: Final = re.compile(r"\$\{[A-Z_][A-Z0-9_]*(?:(?::?[-?])[^}]*)?\}")

#: JSON Schema of ``[tool.pipelines.container].config_mounts``.
CONFIG_MOUNTS_SCHEMA: Final[Mapping[str, object]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "config_mounts",
    "description": "Read-only bind mounts of reference-only configuration directories.",
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "target"],
        "properties": {
            "source": {
                "type": "string",
                "minLength": 1,
                "description": "Absolute host path, or one ${VAR...} compose interpolation.",
            },
            "target": {
                "type": "string",
                "pattern": "^/etc/[^/]",
                "description": "Absolute container directory under /etc.",
            },
        },
    },
}


class ConfigMountError(ValueError):
    """A config mount declaration is malformed or unsafe."""


@dataclass(frozen=True)
class ConfigMount:
    """One read-only bind mount of a configuration directory.

    Args:
        source: Absolute host path, or one ``${VAR...}`` compose interpolation.
        target: Absolute container directory under ``/etc``.
    """

    source: str
    target: str

    def __post_init__(self) -> None:
        if (
            not (
                _INTERPOLATION.fullmatch(self.source)
                or PurePosixPath(self.source).is_absolute()
            )
            or ".." in PurePosixPath(self.source).parts
        ):
            raise ConfigMountError(
                f"config mount source {self.source!r} must be an absolute host path "
                "or one ${VAR} interpolation"
            )
        target = PurePosixPath(self.target)
        if (
            not target.is_absolute()
            or ".." in target.parts
            or str(target) != self.target
        ):
            raise ConfigMountError(
                f"config mount target {self.target!r} must be a normalized absolute path"
            )
        if target.parent == target or CONFIG_ROOT not in target.parents:
            raise ConfigMountError(
                f"config mount target {self.target!r} is not a directory under /etc"
            )


def _entry(raw: object) -> ConfigMount:
    if not isinstance(raw, Mapping) or set(raw) != {"source", "target"}:
        raise ConfigMountError(
            "each config mount is a table of exactly source and target"
        )
    source, target = raw["source"], raw["target"]
    if not isinstance(source, str) or not isinstance(target, str):
        raise ConfigMountError("config mount source and target are strings")
    return ConfigMount(source=source, target=target)


def config_mounts(pyproject: Mapping[str, object]) -> tuple[ConfigMount, ...]:
    """The config mounts declared in a parsed ``pyproject.toml``.

    Raises:
        ConfigMountError: the field is not a list of valid mounts, or two
            mounts share a target.
    """
    tool = pyproject.get("tool")
    pipelines = tool.get("pipelines") if isinstance(tool, Mapping) else None
    container = pipelines.get("container") if isinstance(pipelines, Mapping) else None
    raw = container.get("config_mounts") if isinstance(container, Mapping) else None
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigMountError("config_mounts is a list of tables")
    mounts = tuple(_entry(item) for item in raw)
    targets = [m.target for m in mounts]
    if len(set(targets)) != len(targets):
        raise ConfigMountError("two config mounts share a target")
    return mounts
