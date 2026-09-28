"""In-memory alarm and asset repository with filtering, search and serialisation."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from alarm_api_sim.catalog import ALARM_DEFINITIONS, ASSETS, ASSETS_BY_ID, SEVERITY_RANK, Asset
from alarm_api_sim.seed import AlarmRecord, generate_alarms


class NotFoundError(LookupError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} '{identifier}' not found")
        self.resource = resource
        self.identifier = identifier


def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    words = _TOKEN.findall(text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


class Repository:
    def __init__(self, anchor: datetime, seed: int) -> None:
        self.anchor = anchor
        self.alarms: list[AlarmRecord] = generate_alarms(anchor, seed)
        self.by_id = {a.alarm_id: a for a in self.alarms}
        self._by_key: dict[tuple[str, str], list[AlarmRecord]] = defaultdict(list)
        for alarm in self.alarms:
            self._by_key[(alarm.asset_id, alarm.alarm_code)].append(alarm)

    # -- assets ---------------------------------------------------------------------------

    def asset(self, asset_id: str) -> Asset:
        try:
            return ASSETS_BY_ID[asset_id]
        except KeyError:
            raise NotFoundError("asset", asset_id) from None

    def search_assets(self, query: str, site: str | None, unit: str | None, asset_class: str | None, limit: int) -> list[dict[str, Any]]:
        q_tokens = _tokens(query)
        normalised = query.strip().lower()
        scored = []
        for asset in ASSETS:
            if site and asset.site.lower() != site.lower():
                continue
            if unit and asset.unit.lower() != unit.lower():
                continue
            if asset_class and asset.asset_class != asset_class:
                continue
            strong = _tokens(f"{asset.asset_name} {asset.asset_id} {asset.asset_class.replace('_', ' ')}")
            weak = _tokens(f"{asset.description} {asset.site} {asset.unit}")
            if not q_tokens:
                continue
            score = sum(1.0 if t in strong else 0.4 if t in weak else 0.0 for t in q_tokens) / len(q_tokens)
            if normalised in (asset.asset_name.lower(), asset.asset_id.lower()):
                score += 1.0
            if score >= 0.3:
                scored.append((score, asset))
        scored.sort(key=lambda item: (-item[0], item[1].asset_id))
        return [
            {
                "asset_id": a.asset_id,
                "asset_name": a.asset_name,
                "asset_class": a.asset_class,
                "site": a.site,
                "unit": a.unit,
                "criticality": a.criticality,
                "match_score": round(min(score, 1.0), 3),
                "exact_match": score > 1.0,
            }
            for score, a in scored[:limit]
        ]

    def asset_metadata(self, asset_id: str) -> dict[str, Any]:
        asset = self.asset(asset_id)
        month_ago = self.anchor - timedelta(days=30)
        own = [a for a in self.alarms if a.asset_id == asset_id]
        return {
            "asset_id": asset.asset_id,
            "asset_name": asset.asset_name,
            "asset_class": asset.asset_class,
            "site": asset.site,
            "unit": asset.unit,
            "criticality": asset.criticality,
            "description": asset.description,
            "manufacturer": asset.manufacturer,
            "model": asset.model,
            "install_date": asset.install_date,
            "parent_asset_id": asset.parent_asset_id,
            "attributes": dict(asset.attributes),
            "related_assets": [
                {
                    "asset_id": rid,
                    "asset_name": ASSETS_BY_ID[rid].asset_name,
                    "asset_class": ASSETS_BY_ID[rid].asset_class,
                    "relationship": relationship,
                    "criticality": ASSETS_BY_ID[rid].criticality,
                }
                for rid, relationship in asset.related_assets
                if rid in ASSETS_BY_ID
            ],
            "alarm_statistics": {
                "active_alarms": sum(1 for a in own if a.is_active),
                "alarms_last_30_days": sum(1 for a in own if a.start_time >= month_ago),
                "last_alarm_time": iso(max((a.start_time for a in own), default=None)),
            },
            "maintenance": {
                "last_preventive_maintenance": iso(self.anchor - timedelta(days=17 + len(asset_id) * 3)),
                "running_hours": 20000 + (sum(map(ord, asset_id)) * 37) % 25000,
            },
        }

    # -- alarms ---------------------------------------------------------------------------

    def alarm(self, alarm_id: str) -> AlarmRecord:
        try:
            return self.by_id[alarm_id]
        except KeyError:
            raise NotFoundError("alarm", alarm_id) from None

    def filter_alarms(
        self,
        *,
        asset_ids: Iterable[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        status: str | None = None,
        severities: Iterable[str] | None = None,
        alarm_types: Iterable[str] | None = None,
        alarm_codes: Iterable[str] | None = None,
        min_severity: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[AlarmRecord]:
        ids = set(asset_ids) if asset_ids else None
        sevs = set(severities) if severities else None
        types = set(alarm_types) if alarm_types else None
        codes = set(alarm_codes) if alarm_codes else None
        min_rank = SEVERITY_RANK[min_severity] if min_severity else 0
        result = []
        for alarm in self.alarms:
            asset = ASSETS_BY_ID[alarm.asset_id]
            definition = ALARM_DEFINITIONS[alarm.alarm_code]
            if ids is not None and alarm.asset_id not in ids:
                continue
            if site and asset.site.lower() != site.lower():
                continue
            if unit and asset.unit.lower() != unit.lower():
                continue
            if status == "active" and not alarm.is_active:
                continue
            if status == "cleared" and alarm.is_active:
                continue
            if sevs is not None and definition.severity not in sevs:
                continue
            if types is not None and definition.alarm_type not in types:
                continue
            if codes is not None and alarm.alarm_code not in codes:
                continue
            if SEVERITY_RANK[definition.severity] < min_rank:
                continue
            if start and alarm.start_time < start:
                continue
            if end and alarm.start_time >= end:
                continue
            result.append(alarm)
        return result

    def occurrences(self, asset_id: str, alarm_code: str) -> list[AlarmRecord]:
        return self._by_key[(asset_id, alarm_code)]

    def duration_minutes(self, alarm: AlarmRecord) -> float:
        end = alarm.end_time or self.anchor
        return round((end - alarm.start_time).total_seconds() / 60, 1)

    @staticmethod
    def ack_delay_seconds(alarm: AlarmRecord) -> float | None:
        return round((alarm.ack_time - alarm.start_time).total_seconds(), 1) if alarm.ack_time else None

    def serialize(self, alarm: AlarmRecord) -> dict[str, Any]:
        asset = ASSETS_BY_ID[alarm.asset_id]
        definition = ALARM_DEFINITIONS[alarm.alarm_code]
        state = "active" if alarm.is_active else "cleared"
        return {
            "alarm_id": alarm.alarm_id,
            "asset_id": alarm.asset_id,
            "asset_name": asset.asset_name,
            "asset_class": asset.asset_class,
            "site": asset.site,
            "unit": asset.unit,
            "alarm_code": alarm.alarm_code,
            "alarm_name": definition.alarm_name,
            "alarm_type": definition.alarm_type,
            "severity": definition.severity,
            "priority": definition.priority,
            "is_trip": definition.is_trip,
            "status": state,
            "acknowledged": alarm.ack_time is not None,
            "start_time": iso(alarm.start_time),
            "end_time": iso(alarm.end_time),
            "ack_time": iso(alarm.ack_time),
            "duration_minutes": self.duration_minutes(alarm),
            "ack_delay_seconds": self.ack_delay_seconds(alarm),
            "value": alarm.value,
            "setpoint": definition.setpoint,
            "uom": definition.uom,
            "message": f"{asset.asset_name}: {definition.alarm_name}"
            + (f" ({alarm.value} {definition.uom}, setpoint {definition.setpoint})" if alarm.value is not None else ""),
        }
