"""Bounded, host-admitted NOAA Storm Events archive records."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_connector_sdk.adapters.bookmark_io import _read_file
from agent_connector_sdk.earth_observations.records import WeatherEvent
from agent_connector_sdk.taxonomy.provider import _valid_id


class StormSourceError(RuntimeError):
    """An admitted NOAA archive or one of its records was refused."""


@dataclass(frozen=True)
class StormAdmission:
    """Graph-owned interpretation of one source event and episode."""

    weather_system_id: str
    weather_system_name: str
    place_id: str
    severity: str


@dataclass(frozen=True)
class StormArchivePolicy:
    root: Path
    relative_path: str
    sha256: str
    max_compressed_bytes: int
    max_expanded_bytes: int
    license_tag: str
    timezone_offsets_minutes: Mapping[str, int]


class NoaaStormArchive:
    """Read selected NOAA event IDs from a host-authorized archive."""

    def __init__(
        self,
        policy: StormArchivePolicy,
        admit: Callable[[Mapping[str, str]], StormAdmission | None],
    ) -> None:
        if (
            len(policy.sha256) != 64
            or any(c not in "0123456789abcdef" for c in policy.sha256)
            or policy.max_compressed_bytes < 1
            or policy.max_expanded_bytes < 1
            or not policy.license_tag
            or any(
                type(x) is not int or not -840 <= x <= 840
                for x in policy.timezone_offsets_minutes.values()
            )
        ):
            raise ValueError("invalid storm archive policy")
        self.policy = policy
        self.admit = admit

    def read(
        self, identifiers: Sequence[str], *, tenant: str, source: str, max_records: int
    ) -> tuple[WeatherEvent, ...]:
        if (
            not tenant
            or not source
            or max_records < 1
            or len(identifiers) > max_records
            or len(set(identifiers)) != len(identifiers)
            or any(not _valid_id(item) for item in identifiers)
        ):
            raise ValueError("invalid storm request")
        try:
            return self._read_page(identifiers, tenant=tenant, source=source)
        except Exception:
            raise StormSourceError("storm archive page refused") from None

    def _read_page(
        self, identifiers: Sequence[str], *, tenant: str, source: str
    ) -> tuple[WeatherEvent, ...]:
        raw = _read_file(
            self.policy.root,
            self.policy.relative_path,
            self.policy.max_compressed_bytes,
        )
        if hashlib.sha256(raw).hexdigest() != self.policy.sha256:
            raise ValueError("archive digest mismatch")
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as archive:
            expanded = archive.read(self.policy.max_expanded_bytes + 1)
        if len(expanded) > self.policy.max_expanded_bytes:
            raise ValueError("archive expanded byte limit exceeded")
        reader = csv.DictReader(io.StringIO(expanded.decode("utf-8-sig"), newline=""))
        wanted = set(identifiers)
        records: dict[str, WeatherEvent] = {}
        for row in reader:
            identifier = row.get("EVENT_ID", "")
            if identifier in wanted:
                if identifier in records:
                    raise ValueError("duplicate storm event")
                records[identifier] = self._record(row, tenant, source)
        if records.keys() != wanted:
            raise ValueError("storm event missing")
        return tuple(records[identifier] for identifier in identifiers)

    def _event_time(self, row: dict[str, Any]) -> datetime:
        zone = row["CZ_TIMEZONE"]
        if zone not in self.policy.timezone_offsets_minutes:
            raise ValueError("storm timezone not admitted")
        yearmonth = row["BEGIN_YEARMONTH"]
        if len(yearmonth) != 6 or not yearmonth.isascii() or not yearmonth.isdecimal():
            raise ValueError("invalid storm date")
        clock = int(row["BEGIN_TIME"])
        event_time = datetime(
            int(yearmonth[:4]),
            int(yearmonth[4:]),
            int(row["BEGIN_DAY"]),
            clock // 100,
            clock % 100,
            tzinfo=timezone(
                timedelta(minutes=self.policy.timezone_offsets_minutes[zone])
            ),
        ).astimezone(UTC)
        return event_time

    def _record(self, row: dict[str, Any], tenant: str, source: str) -> WeatherEvent:
        identifier, episode = row["EVENT_ID"], row["EPISODE_ID"]
        if not _valid_id(identifier) or not _valid_id(episode):
            raise ValueError("storm event or episode identity missing")
        admitted = self.admit(row)
        if admitted is None or not all(
            (
                admitted.weather_system_id,
                admitted.weather_system_name,
                admitted.place_id,
                admitted.severity,
            )
        ):
            raise ValueError("storm event not admitted")
        event_time = self._event_time(row)
        return WeatherEvent(
            tenant_id=tenant,
            source_id=source,
            provider="noaa_storm",
            source_event_id=identifier,
            event_time_utc=event_time,
            observed_at_utc=datetime.now(UTC),
            license_tag=self.policy.license_tag,
            source_digest=self.policy.sha256,
            weather_system_id=admitted.weather_system_id,
            weather_system_name=admitted.weather_system_name,
            place_id=admitted.place_id,
            event_type=row["EVENT_TYPE"],
            severity=admitted.severity,
        )
