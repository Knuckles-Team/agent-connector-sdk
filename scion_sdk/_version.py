"""The SDK version, read from installed package metadata.

``pyproject.toml`` is the only file that spells it (SCION-CONNECTOR-CONTROL-R071.2).
"""

from scion_sdk.connector_identity import distribution_version

__version__ = distribution_version("scion-sdk")
