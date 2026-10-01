"""Ref and tree records for the repository walk phase.

A provider lists every ref pinned to an immutable revision, then pages each
revision's tree as ``(path, Git blob object id)`` entries without content, so
the transport can walk a repository's structure before fetching any bytes.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from agent_connector_sdk.repository.identity import _immutable_git_id, _logical_path
from agent_connector_sdk.repository.models import (
    RepositoryRevision,
    _Frozen,
    _PathsPage,
)

__all__ = ["RepositoryRef", "RepositoryTreeEntry", "RepositoryTreePage"]


class RepositoryRef(_Frozen):
    """One branch or tag name resolved to an immutable revision."""

    name: str = Field(min_length=1, max_length=1024)
    revision: RepositoryRevision

    @model_validator(mode="after")
    def _name_is_printable(self) -> Self:
        if any(not char.isprintable() for char in self.name):
            raise ValueError("ref name must be printable")
        return self


class RepositoryTreeEntry(_Frozen):
    """One file path in a revision tree bound to its Git blob object id."""

    path: str
    blob_id: str

    @model_validator(mode="after")
    def _identity_is_immutable(self) -> Self:
        object.__setattr__(self, "path", _logical_path(self.path))
        object.__setattr__(
            self, "blob_id", _immutable_git_id(self.blob_id, field_name="blob_id")
        )
        return self


class RepositoryTreePage(_PathsPage):
    """One bounded page of a revision tree, bound to the requested revision."""

    revision: RepositoryRevision
    entries: tuple[RepositoryTreeEntry, ...] = ()

    def _page_paths(self) -> list[str]:
        return [item.path for item in self.entries]
