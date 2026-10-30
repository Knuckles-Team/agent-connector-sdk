"""Query construction and error classification for algorithm selection."""

from __future__ import annotations

import re

#: Error code the engine returns for a declared but unserved method.
_NOT_SERVED_CODE = "METHOD_NOT_YET_SERVED"
_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+$")


def _iri(value: str, what: str) -> str:
    if not _IRI.match(value):
        raise ValueError(f"{what} must be an absolute IRI")
    return value


def _selection_query(analysis: str, vocabulary: str) -> str:
    return (
        "SELECT ?algorithm ?method ?op WHERE { "
        f"<{analysis}> <{vocabulary}appliesAlgorithm> ?algorithm . "
        f"?algorithm <{vocabulary}servedBy> ?method . "
        f"OPTIONAL {{ ?algorithm <{vocabulary}servedOp> ?op }} "
        "} ORDER BY ?algorithm"
    )


def _is_not_served(exc: BaseException) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    return str(code) == _NOT_SERVED_CODE or _NOT_SERVED_CODE in str(exc)
