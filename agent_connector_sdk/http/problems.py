"""RFC 9457 problem details for upstream HTTP failures.

A response with media type ``application/problem+json`` is parsed into
:class:`ProblemDetails`; anything else, or a malformed problem document, becomes
a problem carrying only the status and its reason phrase. Vendor error bodies
that are not problem documents are never copied into a problem, because they
can echo request data.
"""

from __future__ import annotations

import json
from http import HTTPStatus

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

__all__ = [
    "PROBLEM_JSON",
    "SDK_PROBLEM_TYPE_PREFIX",
    "ProblemDetails",
    "problem_from_response",
]

#: The problem details media type.
PROBLEM_JSON = "application/problem+json"
#: Prefix of the problem types the SDK itself raises.
SDK_PROBLEM_TYPE_PREFIX = "urn:agent-connector-sdk:problem:"

_MAX_TEXT = 2_048
_MAX_EXTENSIONS = 32
_MEMBERS = ("type", "title", "detail", "instance")


def _reason(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "HTTP error"


def _clip(value: str | None) -> str | None:
    return value[:_MAX_TEXT] if value is not None else None


class ProblemDetails(BaseModel):
    """One RFC 9457 problem; extension members are kept in ``extensions``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(default="about:blank", min_length=1, max_length=_MAX_TEXT)
    title: str | None = Field(default=None, max_length=_MAX_TEXT)
    status: int | None = Field(default=None, ge=100, le=599)
    detail: str | None = Field(default=None, max_length=_MAX_TEXT)
    instance: str | None = Field(default=None, max_length=_MAX_TEXT)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def for_status(cls, status: int, **extensions: JsonValue) -> ProblemDetails:
        """An ``about:blank`` problem titled with the status reason phrase."""
        return cls(title=_reason(status), status=status, extensions=extensions)

    @classmethod
    def sdk(
        cls,
        kind: str,
        title: str,
        *,
        detail: str | None = None,
        **extensions: JsonValue,
    ) -> ProblemDetails:
        """A problem the SDK raises itself, typed ``urn:agent-connector-sdk:problem:<kind>``."""
        return cls(
            type=f"{SDK_PROBLEM_TYPE_PREFIX}{kind}",
            title=title,
            detail=_clip(detail),
            extensions=extensions,
        )

    def to_json(self) -> dict[str, JsonValue]:
        """The RFC 9457 JSON object, extension members at the top level."""
        members = self.model_dump(exclude_none=True, exclude={"extensions"})
        return {**self.extensions, **members}


def _json_object(body: bytes) -> dict[str, object] | None:
    try:
        document = json.loads(body)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def _from_document(document: dict[str, object], status: int) -> ProblemDetails:
    members = {key: document[key] for key in _MEMBERS if key in document}
    for key in ("title", "detail"):
        if isinstance(members.get(key), str):
            members[key] = _clip(str(members[key]))
    extensions = {
        key: value
        for key, value in document.items()
        if key not in _MEMBERS and key != "status"
    }
    if len(extensions) > _MAX_EXTENSIONS:
        raise ValueError("too many extension members")
    return ProblemDetails.model_validate(
        {**members, "status": status, "extensions": extensions}
    )


def problem_from_response(response: httpx.Response, body: bytes) -> ProblemDetails:
    """The problem an error response describes.

    ``status`` is always the response's own status code.
    """
    fallback = ProblemDetails.for_status(response.status_code)
    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    if media_type.casefold() != PROBLEM_JSON:
        return fallback
    document = _json_object(body)
    if document is None:
        return ProblemDetails.for_status(response.status_code, malformed_problem=True)
    try:
        return _from_document(document, response.status_code)
    except (ValidationError, ValueError):
        return ProblemDetails.for_status(response.status_code, malformed_problem=True)
