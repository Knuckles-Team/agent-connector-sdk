import gzip
from datetime import UTC, datetime

import pytest
from storm_test_helpers import archive_policy

from agent_connector_sdk.earth_observations.storm import (
    NoaaStormArchive,
    StormAdmission,
    StormSourceError,
)


@pytest.mark.spec("SCION-SOURCE-INGEST-R008")
def test_storm_episode_and_local_time_are_host_admitted(tmp_path):
    body = b"BEGIN_YEARMONTH,BEGIN_DAY,BEGIN_TIME,EPISODE_ID,EVENT_ID,CZ_TIMEZONE,EVENT_TYPE\n202503,1,1630,22,33,CST-6,Tornado\n"
    compressed = gzip.compress(body)
    (tmp_path / "source.csv.gz").write_bytes(compressed)
    policy = archive_policy(tmp_path, compressed)
    requests = []

    def admit(row):
        requests.append(row["EPISODE_ID"])
        return StormAdmission(
            weather_system_id="noaa:22",
            weather_system_name="Approved storm",
            place_id="approved-place",
            severity="EF1",
        )

    source = NoaaStormArchive(policy, admit)
    (record,) = source.read(["33"], tenant="tenant", source="storm", max_records=1)
    assert requests == ["22"]
    assert record.event_time_utc == datetime(2025, 3, 1, 22, 30, tzinfo=UTC)
    assert record.weather_system_id == "noaa:22"
    assert record.severity == "EF1"
    assert record.source_digest == policy.sha256


@pytest.mark.spec("SCION-SOURCE-INGEST-R008")
def test_storm_refuses_missing_episode_and_archive_mutation(tmp_path):
    body = b"BEGIN_YEARMONTH,BEGIN_DAY,BEGIN_TIME,EPISODE_ID,EVENT_ID,CZ_TIMEZONE,EVENT_TYPE\n202503,1,1630,,33,CST-6,Tornado\n"
    compressed = gzip.compress(body)
    path = tmp_path / "source.csv.gz"
    path.write_bytes(compressed)
    policy = archive_policy(tmp_path, compressed)
    source = NoaaStormArchive(
        policy, lambda row: StormAdmission("noaa:22", "name", "place", "EF1")
    )
    with pytest.raises(StormSourceError):
        source.read(["33"], tenant="tenant", source="storm", max_records=1)
    path.write_bytes(gzip.compress(body + b"changed"))
    with pytest.raises(StormSourceError):
        source.read(["33"], tenant="tenant", source="storm", max_records=1)


@pytest.mark.spec("SCION-SOURCE-INGEST-R008")
def test_storm_refuses_traversal_and_expansion_limit(tmp_path):
    compressed = gzip.compress(b"x" * 4096)
    path = tmp_path / "source.csv.gz"
    path.write_bytes(compressed)
    policy = archive_policy(tmp_path, compressed, expanded_limit=64)

    def admission(row):
        return StormAdmission("noaa:1", "name", "place", "EF1")

    source = NoaaStormArchive(policy, admission)
    with pytest.raises(StormSourceError):
        source.read(["1"], tenant="tenant", source="storm", max_records=1)
    policy = archive_policy(tmp_path, compressed, relative_path="../source.csv.gz")
    source = NoaaStormArchive(policy, admission)
    with pytest.raises(StormSourceError):
        source.read(["1"], tenant="tenant", source="storm", max_records=1)
