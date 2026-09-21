"""Typed extension ports (RF-ADR-009 section 2.2.1), one protocol per module.

* :mod:`~agent_connector_sdk.ports.source_adapter`: ``SourceAdapter`` extracts
  records from one source stream.
* :mod:`~agent_connector_sdk.ports.artifact_kind`: ``ArtifactKind`` lists,
  validates and maps one kind of MCP-served content.
* :mod:`~agent_connector_sdk.ports.transport`: ``Transport`` opens sessions.
* :mod:`~agent_connector_sdk.ports.sink`: ``Sink`` durably accepts batches and
  content packs.
* :mod:`~agent_connector_sdk.ports.session`: ``McpSession``, the operations the
  other ports need from a session, and ``TransportEndpoint``.
* :mod:`~agent_connector_sdk.ports.writeback`: ``WriteBackPort`` applies an
  EG-owned source change set through an authorized source transport.
* :mod:`~agent_connector_sdk.ports.errors`: the errors ports raise.

Implementations are discovered through entry points; see
:mod:`agent_connector_sdk.discovery`. A port method either returns a fully
validated value or raises; there is no partial success.
"""
