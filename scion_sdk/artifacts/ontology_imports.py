"""Scope ``owl:imports`` in captured ontologies to the pack that ships them.

epistemic-graph accepts an ``owl:imports`` only when it names an ontology
entry of the same ConnectorPack. Fleet ontologies import shared hub
ontologies, such as ``http://knuckles.team/kg``. The tenant schema composes
every attached pack, so those imports are redundant at pack scope. The pack
builder removes each external import from the ontology body. It records the
external IRI as an ``ontology-import:<iri>`` entry in the ontology entry's
``requires_capabilities`` annotation. A body without external imports stays
byte-identical, so content digests stay deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from functools import partial

from epistemic_graph.generated.connector_pack import PackAnnotations

from scion_sdk._turtle import AccessContractError, parse_graph
from scion_sdk.artifacts._ontology_edits import _ImportSeparators
from scion_sdk.artifacts._ontology_lexer import (
    _OWL_IMPORTS_IRI,
    _PREDICATE,
    _mask_turtle,
)
from scion_sdk.artifacts._ontology_rewrite import _rewrite_import_match
from scion_sdk.contracts import CapturedArtifact

__all__ = ["IMPORT_REQUIREMENT_PREFIX", "scope_ontology_imports"]

IMPORT_REQUIREMENT_PREFIX = "ontology-import:"

_OBJECTS = r"<[^<>\s]*>(?:\s*,\s*<[^<>\s]*>)*"
_TURTLE_GAP = r"(?:[ \t\r\n]+|#[^\n]*(?:\n|$))*"
_TURTLE_OBJECT = r"<[^<>\s]*>"
_TURTLE_OBJECTS = rf"{_TURTLE_OBJECT}(?:{_TURTLE_GAP},{_TURTLE_GAP}{_TURTLE_OBJECT})*"
# One predicate-object list, with the `;` that separates it from a sibling.
_TURTLE_FOLLOWED = re.compile(rf"{_PREDICATE}\s+(?P<objs>{_OBJECTS})\s*;\s*")
# Start at the separating semicolon, consuming only horizontal whitespace
# before it.  A leading ``\s*`` would be able to cross a masked quoted literal
# (whose bytes are deliberately whitespace in the lexer view) and erase part
# of the original literal during surgery.
_TURTLE_PRECEDED = re.compile(rf"[ \t]*;[ \t\r\n]*{_PREDICATE}\s+(?P<objs>{_OBJECTS})")
_TURTLE_ANY = re.compile(rf"{_PREDICATE}{_TURTLE_GAP}(?P<objs>{_TURTLE_OBJECTS})")
# A final import property can be separated from its sibling by a comment.
# ``#`` remains visible in the masked view, so this gap can skip comments
# without allowing a replacement to treat their original bytes as tokens.
_TURTLE_FINAL = re.compile(
    rf";{_TURTLE_GAP}{_PREDICATE}{_TURTLE_GAP}"
    rf"(?P<objs>{_TURTLE_OBJECTS}){_TURTLE_GAP}\."
)
_RDFXML = re.compile(
    r"\s*<owl:imports\s+rdf:resource=\"(?P<iri>[^\"]*)\"\s*/>",
)


def _parsed_imports(text: str) -> frozenset[str] | None:
    """Return parsed ``owl:imports`` IRIs, or ``None`` outside flat Turtle.

    The SDK's existing flat Turtle parser gives simple documents semantic
    prefix expansion and comment/string handling.  Rich ontologies (for
    example, those with triple-quoted literals) use the lexer above as a
    position-preserving fallback; they must never fall back to raw-text regex
    matching.
    """
    try:
        graph = parse_graph(text)
    except AccessContractError:
        return None
    return frozenset(
        value
        for properties in graph.values()
        for value in properties.get(_OWL_IMPORTS_IRI, ())
        if isinstance(value, str)
    )


def _masked_sub(
    text: str,
    pattern: re.Pattern[str],
    replace: Callable[[re.Match[str], str], str],
) -> str:
    """Apply substitutions found in the lexed view to the original text."""
    masked = _mask_turtle(text)
    matches = tuple(pattern.finditer(masked))
    if not matches:
        return text
    chunks: list[str] = []
    cursor = 0
    for match in matches:
        start, end = match.span()
        chunks.append(text[cursor:start])
        chunks.append(replace(match, text))
        cursor = end
    chunks.append(text[cursor:])
    return "".join(chunks)


def _rewrite_turtle(text: str, keep: Callable[[str], bool], dropped: list[str]) -> str:
    parsed = _parsed_imports(text)

    for pattern, separators in (
        (_TURTLE_FOLLOWED, _ImportSeparators(following=True)),
        (_TURTLE_PRECEDED, _ImportSeparators(preceding=True)),
        (_TURTLE_FINAL, _ImportSeparators(preceding=True)),
    ):
        rewrite = partial(
            _rewrite_import_match,
            keep=keep,
            parsed=parsed,
            dropped=dropped,
            separators=separators,
        )
        text = _masked_sub(text, pattern, rewrite)
    return text


def _rewrite_rdfxml(text: str, keep: Callable[[str], bool], dropped: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        iri = match.group("iri")
        if keep(iri):
            return match.group(0)
        dropped.append(iri)
        return ""

    return _RDFXML.sub(replace, text)


def _with_requirements(
    annotations: PackAnnotations, iris: list[str]
) -> PackAnnotations:
    requirements = list(annotations.requires_capabilities or ())
    for iri in sorted(set(iris)):
        token = f"{IMPORT_REQUIREMENT_PREFIX}{iri}"
        if token not in requirements:
            requirements.append(token)
    return annotations.model_copy(update={"requires_capabilities": requirements})


def scope_ontology_imports(
    entry: CapturedArtifact, pack_ontology_uris: Collection[str]
) -> CapturedArtifact:
    """Remove imports outside the pack and record them as requirements.

    Args:
        entry: one captured ``ontology://`` resource.
        pack_ontology_uris: every ontology entry URI in the same pack.

    Returns:
        The entry unchanged when every import names another pack ontology.
        Otherwise a copy with a scoped body and import requirements.
    """

    def keep(iri: str) -> bool:
        return iri != entry.uri and iri in pack_ontology_uris

    dropped: list[str] = []
    if "xml" in entry.media_type:
        body = _rewrite_rdfxml(entry.body, keep, dropped)
    else:
        body = _rewrite_turtle(entry.body, keep, dropped)
    if _TURTLE_ANY.search(_mask_turtle(body)) and "xml" not in entry.media_type:
        # A lone `<s> owl:imports <x> .` statement has no sibling predicate.
        body = _drop_lone_statements(body, keep, dropped)
    if not dropped:
        return entry
    annotations = _with_requirements(entry.annotations, dropped)
    return entry.model_copy(update={"body": body, "annotations": annotations})


_LONE = re.compile(
    rf"^[ \t]*(?:<[^<>\s]*>|[A-Za-z0-9_.-]*:[A-Za-z0-9_.-]*){_TURTLE_GAP}"
    rf"{_PREDICATE}{_TURTLE_GAP}(?P<objs>{_TURTLE_OBJECTS})"
    rf"{_TURTLE_GAP}\.[ \t]*\n?",
    re.MULTILINE,
)


def _drop_lone_statements(
    text: str, keep: Callable[[str], bool], dropped: list[str]
) -> str:
    parsed = _parsed_imports(text)

    return _masked_sub(
        text,
        _LONE,
        lambda match, original: _rewrite_import_match(
            match,
            original,
            keep=keep,
            parsed=parsed,
            dropped=dropped,
            separators=_ImportSeparators(subject=True, terminator=True),
        ),
    )
