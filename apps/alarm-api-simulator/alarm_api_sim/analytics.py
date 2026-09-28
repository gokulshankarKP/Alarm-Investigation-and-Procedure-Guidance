"""Alarm analytics: summary, trends, correlation, flood analysis, rationalization, priority."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from alarm_api_sim.catalog import ALARM_DEFINITIONS, ASSETS_BY_ID, MAX_RESPONSE_MINUTES, SEVERITY_RANK
from alarm_api_sim.repository import Repository, iso
from alarm_api_sim.schemas import (
    CorrelationRequest,
    FloodAnalysisRequest,
    RationalizationRequest,
    SummaryRequest,
    TrendsRequest,
)
from alarm_api_sim.seed import AlarmRecord

SHORT_ALARM_MINUTES = 2.0


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


class Analytics:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self._repeat_flags = self._compute_repeat_flags()

    def _compute_repeat_flags(self) -> dict[str, bool]:
        """An alarm is a *repeat* when the same asset+code fired in the preceding 7 days."""
        flags: dict[str, bool] = {}
        for rows in self.repo._by_key.values():
            for i, alarm in enumerate(rows):
                flags[alarm.alarm_id] = i > 0 and alarm.start_time - rows[i - 1].start_time <= timedelta(days=7)
        return flags

    # -- KPIs -----------------------------------------------------------------------------

    def kpis(self, alarms: list[AlarmRecord], names: Sequence[str]) -> dict[str, Any]:
        n = len(alarms)
        out: dict[str, Any] = {}
        for name in names:
            if name == "alarm_count":
                out[name] = n
            elif name == "critical_count":
                out[name] = sum(ALARM_DEFINITIONS[a.alarm_code].severity == "critical" for a in alarms)
            elif name == "high_count":
                out[name] = sum(ALARM_DEFINITIONS[a.alarm_code].severity == "high" for a in alarms)
            elif name == "active_count":
                out[name] = sum(a.is_active for a in alarms)
            elif name == "recurring_rate":
                out[name] = round(sum(self._repeat_flags[a.alarm_id] for a in alarms) / n, 3) if n else None
            elif name == "avg_ack_delay":
                out["avg_ack_delay_seconds"] = _mean([d for a in alarms if (d := self.repo.ack_delay_seconds(a)) is not None])
            elif name == "avg_duration":
                out["avg_duration_minutes"] = _mean([self.repo.duration_minutes(a) for a in alarms])
            elif name == "unacknowledged_rate":
                out[name] = round(sum(a.ack_time is None for a in alarms) / n, 3) if n else None
            elif name == "suppression_candidate_rate":
                out[name] = round(sum(self._is_suppression_candidate(a) for a in alarms) / n, 3) if n else None
        return out

    def _is_suppression_candidate(self, alarm: AlarmRecord) -> bool:
        return not alarm.is_active and alarm.ack_time is None and self.repo.duration_minutes(alarm) < SHORT_ALARM_MINUTES

    def _scoped(self, req: Any, *, severities=None, alarm_types=None, min_severity=None) -> list[AlarmRecord]:
        return self.repo.filter_alarms(
            asset_ids=req.asset_ids,
            site=req.site,
            unit=req.unit,
            severities=severities,
            alarm_types=alarm_types,
            min_severity=min_severity,
            start=req.time_range.start_time,
            end=req.time_range.end_time,
        )

    # -- summary / trends -------------------------------------------------------------------

    def summary(self, req: SummaryRequest) -> dict[str, Any]:
        alarms = self._scoped(req, severities=req.severity, alarm_types=req.alarm_types)
        groups: dict[tuple, list[AlarmRecord]] = defaultdict(list)
        for alarm in alarms:
            row = self.repo.serialize(alarm)
            groups[tuple(row[g] for g in req.group_by)].append(alarm)
        group_rows = (
            [{"group": dict(zip(req.group_by, key, strict=True)), **self.kpis(rows, req.kpis)} for key, rows in groups.items()]
            if req.group_by
            else []
        )
        group_rows.sort(key=lambda g: -len(groups[tuple(g["group"].values())]))
        top_codes = Counter((a.asset_id, a.alarm_code) for a in alarms).most_common(5)
        return {
            "totals": self.kpis(alarms, req.kpis),
            "groups": group_rows,
            "top_alarms": [
                {
                    "asset_id": asset,
                    "alarm_code": code,
                    "alarm_name": ALARM_DEFINITIONS[code].alarm_name,
                    "severity": ALARM_DEFINITIONS[code].severity,
                    "count": count,
                }
                for (asset, code), count in top_codes
            ],
        }

    def trends(self, req: TrendsRequest) -> dict[str, Any]:
        alarms = self._scoped(req, severities=req.severity)
        size = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(weeks=1)}[req.bucket]
        start = req.time_range.start_time
        n_buckets = max(1, int((req.time_range.end_time - start) / size + 0.999))
        if n_buckets > 5000:
            raise ValueError("time range too large for the requested bucket size (max 5000 buckets)")
        buckets: list[list[AlarmRecord]] = [[] for _ in range(n_buckets)]
        for alarm in alarms:
            idx = int((alarm.start_time - start) / size)
            if 0 <= idx < n_buckets:
                buckets[idx].append(alarm)

        kpi_names = [m for m in req.metrics]
        series = []
        for i, rows in enumerate(buckets):
            series.append({"bucket_start": iso(start + i * size), **self.kpis(rows, kpi_names)})

        trend: dict[str, dict[str, Any]] = {}
        for metric in kpi_names:
            key = {"avg_ack_delay": "avg_ack_delay_seconds", "avg_duration": "avg_duration_minutes"}.get(metric, metric)
            values = [p[key] or 0 for p in series]
            half = len(values) // 2
            first, second = (_mean(values[:half]) or 0.0), (_mean(values[half:]) or 0.0)
            change = (second - first) / first if first else (1.0 if second else 0.0)
            direction = "increasing" if change > 0.2 else "decreasing" if change < -0.2 else "stable"
            trend[key] = {"direction": direction, "first_half_avg": first, "second_half_avg": second, "relative_change": round(change, 3)}
        return {"bucket": req.bucket, "series": series, "trend": trend, "total_alarms": len(alarms)}

    # -- correlation ------------------------------------------------------------------------

    def correlation(self, req: CorrelationRequest) -> dict[str, Any]:
        for asset_id in req.asset_ids:
            self.repo.asset(asset_id)  # 404 on unknown asset
        focus = set(req.asset_ids)
        scope = set(focus)
        if req.include_related:
            for asset_id in req.asset_ids:
                scope.update(rid for rid, _ in ASSETS_BY_ID[asset_id].related_assets)
        alarms = sorted(
            self.repo.filter_alarms(
                asset_ids=scope, min_severity=req.severity_threshold, start=req.time_range.start_time, end=req.time_range.end_time
            ),
            key=lambda a: a.start_time,
        )
        lag = timedelta(minutes=req.lag_window_minutes)
        key_counts = Counter((a.asset_id, a.alarm_code) for a in alarms)
        pair_hits: dict[tuple, list[float]] = defaultdict(list)
        for i, a in enumerate(alarms):
            seen: set[tuple] = set()
            for b in alarms[i + 1 :]:
                if b.start_time - a.start_time > lag:
                    break
                kb = (b.asset_id, b.alarm_code)
                if kb == (a.asset_id, a.alarm_code) or kb in seen:
                    continue
                seen.add(kb)
                pair_hits[((a.asset_id, a.alarm_code), kb)].append((b.start_time - a.start_time).total_seconds() / 60)

        pairs = []
        for (ka, kb), lags in pair_hits.items():
            if len(lags) < req.min_support or not ({ka[0], kb[0]} & focus):
                continue
            confidence = len(lags) / key_counts[ka]
            pairs.append(
                {
                    "antecedent": {"asset_id": ka[0], "alarm_code": ka[1]},
                    "consequent": {"asset_id": kb[0], "alarm_code": kb[1]},
                    "support": len(lags),
                    "confidence": round(confidence, 3),
                    "median_lag_minutes": round(statistics.median(lags), 1),
                    "cross_asset": ka[0] != kb[0],
                }
            )
        pairs.sort(key=lambda p: (-(p["support"] * p["confidence"]), -p["support"]))
        pairs = pairs[:25]

        # Assets outside the focus set whose alarms precede alarms on 2+ focus assets, or
        # that precede focus alarms with high confidence, are common-cause candidates.
        upstream: dict[str, dict[str, Any]] = {}
        for p in pairs:
            src, dst = p["antecedent"]["asset_id"], p["consequent"]["asset_id"]
            if src not in focus and dst in focus and p["confidence"] >= 0.3:  # upstream of the analysed assets
                entry = upstream.setdefault(src, {"asset_id": src, "affected_assets": set(), "evidence": 0})
                entry["affected_assets"].add(dst)
                entry["evidence"] += p["support"]
        common = [
            {**e, "asset_name": ASSETS_BY_ID[e["asset_id"]].asset_name, "affected_assets": sorted(e["affected_assets"])}
            for e in sorted(upstream.values(), key=lambda e: -e["evidence"])
        ]

        insights = []
        for p in pairs[:6]:
            a, b = p["antecedent"], p["consequent"]
            insights.append(
                f"{a['asset_id']} {a['alarm_code']} is followed by {b['asset_id']} {b['alarm_code']} within "
                f"{req.lag_window_minutes} min in {p['confidence']:.0%} of cases "
                f"(n={p['support']}, median lag {p['median_lag_minutes']} min)"
            )
        for c in common[:3]:
            insights.append(
                f"{c['asset_id']} ({c['asset_name']}) alarms precede alarms on {', '.join(c['affected_assets'])}: possible common cause"
            )
        return {
            "correlation_method": req.correlation_method,
            "lag_window_minutes": req.lag_window_minutes,
            "assets_analyzed": sorted(scope),
            "alarms_analyzed": len(alarms),
            "pairs": pairs,
            "common_cause_candidates": common,
            "insights": insights,
        }

    # -- flood analysis ---------------------------------------------------------------------

    def flood_analysis(self, req: FloodAnalysisRequest) -> dict[str, Any]:
        alarms = sorted(self._scoped(req), key=lambda a: a.start_time)
        window = timedelta(minutes=req.rolling_window_minutes)
        floods: list[list[AlarmRecord]] = []
        j = 0
        for i in range(len(alarms)):
            while alarms[i].start_time - alarms[j].start_time > window:
                j += 1
            if i - j + 1 > req.threshold_count:  # ALM-PHIL-001: "more than N alarms"
                members = alarms[j : i + 1]
                if floods and members[0].start_time <= floods[-1][-1].start_time:
                    floods[-1].extend(a for a in members if a not in floods[-1])
                else:
                    floods.append(list(members))

        total = (req.time_range.end_time - req.time_range.start_time).total_seconds()
        in_flood = sum(max((f[-1].start_time - f[0].start_time).total_seconds(), 60) for f in floods)
        return {
            "threshold_count": req.threshold_count,
            "rolling_window_minutes": req.rolling_window_minutes,
            "total_alarms": len(alarms),
            "flood_count": len(floods),
            "percent_time_in_flood": round(100 * in_flood / total, 4) if total else 0.0,
            "flood_windows": [
                {
                    "start": iso(f[0].start_time),
                    "end": iso(f[-1].start_time),
                    "alarm_count": len(f),
                    "initiating_alarm": self.repo.serialize(f[0]),
                    "assets_involved": sorted({a.asset_id for a in f}),
                    "top_alarm_codes": [c for c, _ in Counter(a.alarm_code for a in f).most_common(5)],
                }
                for f in floods
            ],
        }

    # -- rationalization --------------------------------------------------------------------

    def rationalization(self, req: RationalizationRequest) -> dict[str, Any]:
        alarms = self._scoped(req)
        groups: dict[tuple[str, str], list[AlarmRecord]] = defaultdict(list)
        for alarm in alarms:
            groups[(alarm.asset_id, alarm.alarm_code)].append(alarm)

        chatter_window = timedelta(minutes=req.chatter_window_minutes)
        candidates: list[dict[str, Any]] = []
        for (asset_id, code), rows in groups.items():
            rows.sort(key=lambda a: a.start_time)
            max_7d, j = 0, 0
            chatter_events, k = 0, 0
            for i, alarm in enumerate(rows):
                while alarm.start_time - rows[j].start_time > timedelta(days=7):
                    j += 1
                max_7d = max(max_7d, i - j + 1)
                while alarm.start_time - rows[k].start_time > chatter_window:
                    k += 1
                if i - k + 1 >= req.chatter_threshold:
                    chatter_events += 1
            stale = [a for a in rows if a.is_active and self.repo.duration_minutes(a) > req.stale_minutes_threshold]
            no_action = sum(self._is_suppression_candidate(a) for a in rows)

            reasons = []
            if max_7d >= req.recurrence_threshold:
                reasons.append("recurring")
            if chatter_events:
                reasons.append("chattering")
            if stale:
                reasons.append("stale")
            if len(rows) >= 3 and no_action / len(rows) >= 0.5:
                reasons.append("cleared_without_operator_action")
            if not reasons:
                continue
            definition = ALARM_DEFINITIONS[code]
            candidates.append(
                {
                    "asset_id": asset_id,
                    "asset_name": ASSETS_BY_ID[asset_id].asset_name,
                    "alarm_code": code,
                    "alarm_name": definition.alarm_name,
                    "severity": definition.severity,
                    "reasons": reasons,
                    "occurrences": len(rows),
                    "max_occurrences_in_7_days": max_7d,
                    "chatter_events": chatter_events,
                    "stale_active_minutes": max((self.repo.duration_minutes(a) for a in stale), default=0),
                    "cleared_without_action": no_action,
                    "suggested_review": _review_suggestion(reasons),
                }
            )
        candidates.sort(key=lambda c: (-len(c["reasons"]), -c["occurrences"]))
        return {
            "criteria": {
                "recurrence_threshold_per_7_days": req.recurrence_threshold,
                "stale_minutes_threshold": req.stale_minutes_threshold,
                "chatter": f">= {req.chatter_threshold} activations in {req.chatter_window_minutes} min",
            },
            "alarms_analyzed": len(alarms),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    # -- priority scoring (ALM-PHIL-001 section 4) -----------------------------------------

    def priority_score(self, alarm_id: str) -> dict[str, Any]:
        alarm = self.repo.alarm(alarm_id)
        definition = ALARM_DEFINITIONS[alarm.alarm_code]
        asset = ASSETS_BY_ID[alarm.asset_id]
        now = self.repo.anchor

        severity_pts = {"critical": 40, "high": 30, "medium": 18, "low": 8}[definition.severity]
        criticality_pts = {"A": 25, "B": 15, "C": 5}[asset.criticality]

        max_response = MAX_RESPONSE_MINUTES[definition.severity]
        if alarm.ack_time is None and alarm.is_active:
            unacked_min = (now - alarm.start_time).total_seconds() / 60
        elif alarm.ack_time is not None:
            unacked_min = (alarm.ack_time - alarm.start_time).total_seconds() / 60
        else:
            unacked_min = self.repo.duration_minutes(alarm)
        duration_pts = 15 * min(unacked_min / max_response, 1.0)

        day_before = alarm.start_time - timedelta(hours=24)
        recurrence = sum(
            1 for a in self.repo.occurrences(alarm.asset_id, alarm.alarm_code) if day_before <= a.start_time < alarm.start_time
        )
        recurrence_pts = 10 * min(recurrence / 3, 1.0)

        related_ids = {rid for rid, _ in asset.related_assets} | {alarm.asset_id}
        related_active = [
            a
            for a in self.repo.alarms
            if a.asset_id in related_ids
            and a.alarm_id != alarm.alarm_id
            and a.start_time <= alarm.start_time + timedelta(minutes=15)
            and (a.end_time is None or a.end_time >= alarm.start_time)
            and a.start_time >= alarm.start_time - timedelta(hours=12)
        ]
        related_pts = 10 * min(len(related_active) / 3, 1.0)

        score = round(severity_pts + criticality_pts + duration_pts + recurrence_pts + related_pts, 1)
        band = "urgent" if score >= 80 else "high" if score >= 60 else "medium" if score >= 40 else "low"
        components = [
            {
                "factor": "configured_severity",
                "weight_pct": 40,
                "points": severity_pts,
                "detail": f"severity={definition.severity} (priority {definition.priority})",
            },
            {
                "factor": "asset_criticality",
                "weight_pct": 25,
                "points": criticality_pts,
                "detail": f"{asset.asset_id} criticality {asset.criticality}",
            },
            {
                "factor": "duration_unacknowledged",
                "weight_pct": 15,
                "points": round(duration_pts, 1),
                "detail": f"{unacked_min:.0f} min unacknowledged vs {max_response} min max response time",
            },
            {
                "factor": "recurrence_24h",
                "weight_pct": 10,
                "points": round(recurrence_pts, 1),
                "detail": f"{recurrence} previous occurrence(s) of {alarm.alarm_code} on {alarm.asset_id} in 24 h",
            },
            {
                "factor": "related_active_alarms",
                "weight_pct": 10,
                "points": round(related_pts, 1),
                "detail": f"{len(related_active)} concurrent alarm(s) on this or connected assets",
            },
        ]
        return {
            "alarm_id": alarm.alarm_id,
            "asset_id": alarm.asset_id,
            "alarm_code": alarm.alarm_code,
            "configured_priority": definition.priority,
            "severity": definition.severity,
            "priority_score": score,
            "priority_band": band,
            "components": components,
            "related_active_alarm_ids": [a.alarm_id for a in related_active][:10],
            "rationale": (
                f"{alarm.alarm_code} on {alarm.asset_id} scores {score}/100: "
                + "; ".join(f"{c['factor']} {c['points']} pts" for c in components)
            ),
            "scored_at": iso(now),
        }


def _review_suggestion(reasons: list[str]) -> str:
    parts = []
    if "chattering" in reasons or "cleared_without_operator_action" in reasons:
        parts.append("review setpoint, deadband and on/off delay")
    if "recurring" in reasons:
        parts.append("investigate the recurring root cause and consider state-based suppression")
    if "stale" in reasons:
        parts.append("resolve or return the stale alarm to normal; confirm it still requires operator action")
    return "; ".join(parts).capitalize()


def severity_at_least(severity: str, threshold: str) -> bool:
    return SEVERITY_RANK[severity] >= SEVERITY_RANK[threshold]


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
