"""Build an installed-looking fixture connector distribution in a temp directory."""

from __future__ import annotations

import textwrap
from pathlib import Path

ONTOLOGY = """\
@prefix kg: <http://knuckles.team/kg#> .
@prefix demo: <https://example.invalid/ontology/demo#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

demo:DemoItem a owl:Class ; rdfs:subClassOf kg:Document .
demo:DemoLeaf a owl:Class ; rdfs:subClassOf demo:DemoItem .
"""

ORPHAN = ONTOLOGY + "demo:Lonely a owl:Class .\n"

INIT = """\
from agent_connector_sdk.connector import Connector

from democonn.client import Api, get_client

connector = Connector(api=Api, get_client=get_client, instructions="Demo connector.")
"""

CLIENT = '''\
class Api:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def list_items(self) -> list[dict[str, str]]:
        """List the demo items."""
        return [{"id": "1"}]


def get_client() -> Api:
    return Api()
'''

SOURCES = """\
from agent_connector_sdk.ingest.live_declaration import source_meta

SCHEMA_VERSION = 2
FIELD_SETS = {"common": {"name": "xsd:string", "created": "xsd:dateTime"}}

SOURCES = (
    source_meta(
        tool="demo_list_items",
        source_id="demo-items",
        record_type="DemoItem",
        id_field="id",
    ),
)

SCHEMA_MAPPINGS = {
    "DemoItem": {"ontology_class": "DemoItem", "field_sets": ["common"], "fields": {"size": "xsd:long"}},
    "DemoLeaf": {"ontology_class": "DemoLeaf", "field_sets": ["common"]},
}
RESOURCES = ()
"""

PROMPT = (
    '{"task": "demo", "type": "prompt", "description": "Demo.", '
    '"instructions": {"core_directive": "Operate the demo."}}'
)
SKILL = "---\nname: demo-skill\ndescription: Demo skill.\n---\n# Demo\n"


def build(
    root: Path,
    *,
    version: str = "1.2.3",
    ontology: str = ONTOLOGY,
    init: str = INIT,
    sources: str | None = SOURCES,
    extra_group: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Write package ``democonn`` plus ``democonn-<version>.dist-info`` under ``root``."""
    pkg = root / "democonn"
    for sub in ("skills/demo-skill", "prompts", "ontology"):
        (pkg / sub).mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(init)
    (pkg / "client.py").write_text(CLIENT)
    (pkg / "skills/demo-skill/SKILL.md").write_text(SKILL)
    (pkg / "prompts/demo.json").write_text(PROMPT)
    (pkg / "ontology/demo.ttl").write_text(ontology)
    if sources is not None:
        (pkg / "connector_sources.py").write_text(sources)
    for name, text in (extra_files or {}).items():
        (pkg / name).write_text(text)
    dist = root / f"democonn-{version}.dist-info"
    dist.mkdir(exist_ok=True)
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: democonn\nVersion: {version}\n"
    )
    (dist / "entry_points.txt").write_text(
        "[agent_connector_sdk.connector]\ndemo-mcp = democonn:connector\n"
        + (f"[{extra_group}]\ndemo-mcp = democonn.skills\n" if extra_group else "")
    )
    extra = (
        f'[project.entry-points."{extra_group}"]\ndemo-mcp = "democonn.skills"'
        if extra_group
        else ""
    )
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "democonn"
            version = "{version}"

            [project.entry-points."agent_connector_sdk.connector"]
            demo-mcp = "democonn:connector"
            {extra}
            """
        )
    )
    return root
