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

from epistemic_graph.generated.connector_pack import PackAnnotations

from agent_connector_sdk.contracts import CapturedArtifact

__all__ = ["IMPORT_REQUIREMENT_PREFIX", "scope_ontology_imports"]

IMPORT_REQUIREMENT_PREFIX = "ontology-import:"

_PREDICATE = r"(?:owl:imports|<http://www\.w3\.org/2002/07/owl#imports>)"
_OBJECTS = r"<[^<>\s]*>(?:\s*,\s*<[^<>\s]*>)*"
# One predicate-object list, with the `;` that separates it from a sibling.
_TURTLE_FOLLOWED = re.compile(rf"{_PREDICATE}\s+(?P<objs>{_OBJECTS})\s*;\s*")
_TURTLE_PRECEDED = re.compile(rf"\s*;\s*{_PREDICATE}\s+(?P<objs>{_OBJECTS})")
_TURTLE_ANY = re.compile(rf"{_PREDICATE}\s+(?P<objs>{_OBJECTS})")
_IRI = re.compile(r"<([^<>\s]*)>")
_RDFXML = re.compile(
    r"\s*<owl:imports\s+rdf:resource=\"(?P<iri>[^\"]*)\"\s*/>",
)


def _rewrite_turtle(text: str, keep: Callable[[str], bool], dropped: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        iris = _IRI.findall(match.group("objs"))
        kept = [iri for iri in iris if keep(iri)]
        dropped.extend(iri for iri in iris if not keep(iri))
        if len(kept) == len(iris):
            return match.group(0)
        if kept:
            objs = ", ".join(f"<{iri}>" for iri in kept)
            start, end = match.span("objs")
            whole = match.group(0)
            offset = match.start()
            return whole[: start - offset] + objs + whole[end - offset :]
        return ""

    for pattern in (_TURTLE_FOLLOWED, _TURTLE_PRECEDED):
        text = pattern.sub(replace, text)
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
    if _TURTLE_ANY.search(body) and "xml" not in entry.media_type:
        # A lone `<s> owl:imports <x> .` statement has no sibling predicate.
        body = _drop_lone_statements(body, keep, dropped)
    if not dropped:
        return entry
    annotations = _with_requirements(entry.annotations, dropped)
    return entry.model_copy(update={"body": body, "annotations": annotations})


_LONE = re.compile(
    rf"^[ \t]*(?:<[^<>\s]*>|[A-Za-z0-9_.-]*:[A-Za-z0-9_.-]*)\s+{_PREDICATE}\s+"
    rf"(?P<objs>{_OBJECTS})\s*\.[ \t]*\n?",
    re.MULTILINE,
)


def _drop_lone_statements(
    text: str, keep: Callable[[str], bool], dropped: list[str]
) -> str:
    def replace(match: re.Match[str]) -> str:
        iris = _IRI.findall(match.group("objs"))
        if all(keep(iri) for iri in iris):
            return match.group(0)
        dropped.extend(iri for iri in iris if not keep(iri))
        kept = [iri for iri in iris if keep(iri)]
        if not kept:
            return ""
        objs = ", ".join(f"<{iri}>" for iri in kept)
        return match.group(0).replace(match.group("objs"), objs)

    return _LONE.sub(replace, text)
