"""Record-shaping helpers for the ServiceNow extractor."""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import Entity, Relationship

_DOMAIN = "servicenow"


def _get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _ref(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value") or value.get("display_value")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first(record: Any, *keys: str) -> str | None:
    for key in keys:
        value = _ref(_get(record, key))
        if value:
            return value
    return None


def _key(record: Any) -> str | None:
    return _ref(_get(record, "sys_id")) or _ref(_get(record, "number"))


def _risk_props(record: Any) -> dict[str, Any]:
    """Lifecycle/risk attributes (vendor-neutral TRM props), field-tolerant."""
    out: dict[str, Any] = {}
    stage = _first(
        record, "lifecycle_stage", "lifecycle", "install_status", "life_cycle_stage"
    )
    if stage:
        out["lifecycleStage"] = stage
    eol = _first(
        record, "end_of_life", "eol_date", "end_of_support", "decommission_date"
    )
    if eol:
        out["endOfLifeDate"] = eol
    rating = _first(record, "risk_rating", "risk", "risk_score")
    if rating:
        out["riskRating"] = rating
    return out


def _federation(raw_id: str, **extra: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {"externalToolId": raw_id, "domain": _DOMAIN}
    properties.update({key: value for key, value in extra.items() if value is not None})
    return properties


def _ci_properties(key: str, record: Any, risk: dict[str, Any]) -> dict[str, Any]:
    return _federation(
        key,
        name=_get(record, "name"),
        short_description=_get(record, "short_description"),
        ci_class=_ref(_get(record, "ci_class")),
        state=_ref(_get(record, "state")),
        **risk,
    )


def _model_properties(key: str, record: Any, risk: dict[str, Any]) -> dict[str, Any]:
    return _federation(
        key,
        name=_first(record, "display_name", "name"),
        manufacturer=_first(record, "manufacturer", "vendor"),
        **risk,
    )


def _asset_properties(key: str, record: Any, risk: dict[str, Any]) -> dict[str, Any]:
    return _federation(
        key,
        name=_first(record, "display_name", "name", "asset_tag"),
        **risk,
    )


def _risk_entities(
    owner_id: str, record: Any, risk: dict[str, Any]
) -> tuple[list[Entity], list[Relationship]]:
    """A TechnologyRisk entity + HAS_RISK relationship on risk/EOL signal."""
    if not (risk.get("riskRating") or risk.get("endOfLifeDate")):
        return [], []
    risk_id = f"snrisk:{owner_id}"
    entity = Entity(
        id=risk_id,
        node_type="TechnologyRisk",
        properties=_federation(
            owner_id,
            name=f"Risk: {_get(record, 'name') or owner_id}",
            **risk,
        ),
    )
    rel = Relationship(source=owner_id, target=risk_id, relationship="HAS_RISK")
    return [entity], [rel]
