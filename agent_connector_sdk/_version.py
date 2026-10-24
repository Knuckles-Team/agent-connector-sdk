"""The SDK version, read from installed package metadata.

``pyproject.toml`` is the only file that spells it (SDK-CONNECTOR-CONTROL-R071.2).
"""

from agent_connector_sdk.connector_identity import distribution_version

__version__ = distribution_version("agent-connector-sdk")
