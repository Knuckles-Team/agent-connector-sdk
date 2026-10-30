"""The connector-sync runner (RF-ADR-009 sections 2.1 and 2.2).

One supervised scheduler serves every connector: it opens one MCP session per
connector through the ``Transport`` port, provisions the connector's content
pack when its digest changed, runs the manifest ``sync`` presets through the
``mcp_tool`` adapter with EG-authoritative checkpoints, and reacts to the
server's change events, falling back to its schedule.

* :mod:`~scion_sdk.runner.descriptors`: connector descriptors and settings.
* :mod:`~scion_sdk.runner.static_registry`: the configuration-file registry.
* :mod:`~scion_sdk.runner.provisioning` and
  :mod:`~scion_sdk.runner.syncing`: one provisioning and one sync pass.
* :mod:`~scion_sdk.runner.worker`: one connector's supervised loop.
* :mod:`~scion_sdk.runner.supervisor`: the scheduler over all connectors.
* :mod:`~scion_sdk.runner.cli`: the ``connector-sync`` console script.
"""
