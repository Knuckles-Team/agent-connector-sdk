"""Data-only subpackage that contributes the ``agent-connector-sdk-development``
skill to the arbora skill federation via the ``agent_connector_sdk.skill_providers``
entry-point, exactly like ``epistemic_graph.skills`` and ``agent_webui.skills``.
Carries no runtime imports — the hub resolves this package's directory through
``importlib.resources`` and reads the ``SKILL.md`` file; it never executes SDK
business logic. Declaring the entry point does not add ``agent-utilities`` as a
dependency of this package: a consumer that already has agent-utilities
installed discovers the entry point as metadata.
"""
