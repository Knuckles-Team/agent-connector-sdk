"""Exception types and the authentication guard connectors raise and use.

Extracted from ``agent_utilities.core.exceptions`` and
``agent_utilities.core.decorators.require_auth``. The class hierarchy is kept
identical so connector ``except`` clauses keep their meaning after the import
path changes.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Concatenate, Protocol

__all__ = [
    "ApiError",
    "AuthError",
    "LoginRequiredError",
    "MissingParameterError",
    "ParameterError",
    "UnauthorizedError",
    "require_auth",
]


class AuthError(Exception):
    """Base exception for all authentication-related errors."""


class ApiError(Exception):
    """An external API call failed or returned an error."""


class UnauthorizedError(AuthError):
    """Access was denied because of insufficient permissions or bad credentials."""


class MissingParameterError(Exception):
    """A required parameter was not supplied."""


class ParameterError(Exception):
    """A supplied parameter is invalid or has the wrong format."""


class LoginRequiredError(Exception):
    """An action requires authentication, but no credentials are present."""


class _HasHeaders(Protocol):
    headers: Any


def require_auth[S: _HasHeaders, **P, R](
    function: Callable[Concatenate[S, P], R],
) -> Callable[Concatenate[S, P], R]:
    """Refuse to call an API-client method until ``self.headers`` is populated.

    Raises:
        LoginRequiredError: when the client instance has empty ``headers``.
    """

    @functools.wraps(function)
    def wrapper(self: S, /, *args: P.args, **kwargs: P.kwargs) -> R:
        if not self.headers:
            raise LoginRequiredError
        return function(self, *args, **kwargs)

    return wrapper
