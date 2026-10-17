"""Typed finance provider errors.

An unconfigured or failing provider raises one of these instead of returning
a placeholder value.
"""

from __future__ import annotations


class FinanceProviderError(RuntimeError):
    """Base class for finance data-provider failures."""


class ProviderNotConfigured(FinanceProviderError):
    """A provider was invoked without the credentials/config it requires.

    The message must name the exact env var / config key the caller should set.
    """


class ProviderRequestError(FinanceProviderError):
    """A configured provider was reached but the request failed."""


class InvalidIntervalError(ValueError, FinanceProviderError):
    """A gap-fill/ASOF interval was empty, malformed, zero, or negative.

    Subclasses ``ValueError`` so callers that catch malformed input keep working.
    """
