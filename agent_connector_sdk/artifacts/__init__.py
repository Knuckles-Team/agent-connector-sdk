"""The four MCP artifact kinds (``agent_connector_sdk.artifact_kinds`` entry points).

RF-ADR-009 section 2.1. Each kind reads its listing from the *same* MCP session an
agent would use, so what is provisioned is exactly what the server serves:

========  ==============================================  ===================
Kind      MCP primitive                                   Record kind
========  ==============================================  ===================
tool      ``tools/list``                                  ``Tool``
skill     ``skill://<name>/SKILL.md`` resources           ``Skill``
prompt    ``prompts/list``                                ``McpPrompt``
resource  ``resources/list`` + ``resources/read``         by URI scheme
========  ==============================================  ===================

:func:`agent_connector_sdk.artifacts.pack.build_content_pack` assembles a
validated generated ConnectorPack archive from any kinds.
"""
