"""Shared bounded NOAA archive policies for source tests."""

import hashlib

from agent_connector_sdk.earth_observations.storm import StormArchivePolicy


def archive_policy(
    root, compressed, *, relative_path="source.csv.gz", expanded_limit=4096
):
    return StormArchivePolicy(
        root=root,
        relative_path=relative_path,
        sha256=hashlib.sha256(compressed).hexdigest(),
        max_compressed_bytes=4096,
        max_expanded_bytes=expanded_limit,
        license_tag="admitted",
        timezone_offsets_minutes={"CST-6": -360},
    )
