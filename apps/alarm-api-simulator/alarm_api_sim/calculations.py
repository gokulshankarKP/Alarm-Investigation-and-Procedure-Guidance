"""KPI calculation-code generation and execution.

``generate`` returns a *read-only* code listing describing the calculation and stores a
calculation id. ``execute`` runs the corresponding built-in implementation; submitted code
is never evaluated, so the endpoint cannot be used to run arbitrary code.
"""

from __future__ import annotations

import textwrap
import uuid
from datetime import datetime
from typing import Any

from alarm_api_sim.analytics import Analytics
from alarm_api_sim.catalog import ALARM_DEFINITIONS, MAX_RESPONSE_MINUTES
from alarm_api_sim.repository import NotFoundError, Repository, iso
from alarm_api_sim.schemas import CalculationFilters, FloodAnalysisRequest, TimeRange

KPI_DEFINITIONS: list[dict[str, Any]] = [
    {
        "kpi": "average_alarm_rate",
        "description": "Average alarms per operator console per 10 minutes",
        "formula": "alarm_count / (window_minutes / 10)",
        "target": "<= 1",
        "action_threshold": "> 2 sustained over a shift",
        "unit": "alarms/10 min",
        "source": "ALM-PHIL-001 section 8",
    },
    {
        "kpi": "alarm_flood_index",
        "description": "Percentage of time in alarm flood (> 10 alarms in 10 minutes)",
        "formula": "sum(flood_window_duration) / window_duration * 100",
        "target": "< 1 %",
        "action_threshold": "> 1 % in a month",
        "unit": "%",
        "source": "ALM-PHIL-001 sections 6 and 8",
    },
    {
        "kpi": "critical_alarm_density",
        "description": "Share of alarms configured as priority 1 (critical)",
        "formula": "critical_count / alarm_count * 100",
        "target": "< 5 %",
        "action_threshold": ">= 5 %",
        "unit": "%",
        "source": "ALM-PHIL-001 section 3",
    },
    {
        "kpi": "operator_response_efficiency",
        "description": "Share of acknowledged alarms acknowledged within the maximum response time for their priority",
        "formula": "count(ack_delay <= max_response(severity)) / count(acknowledged) * 100",
        "target": ">= 95 %",
        "action_threshold": "< 90 %",
        "unit": "%",
        "source": "ALM-PHIL-001 section 3",
    },
    {
        "kpi": "nuisance_alarm_score",
        "description": "0-100 score of nuisance behaviour: short alarms cleared without action and chattering",
        "formula": "100 * (short_unacknowledged + chattering_activations) / alarm_count (capped at 100)",
        "target": "< 10",
        "action_threshold": ">= 25",
        "unit": "score",
        "source": "ALM-PHIL-001 section 8",
    },
    {
        "kpi": "avg_ack_delay",
        "description": "Average acknowledgement delay",
        "formula": "mean(ack_time - start_time)",
        "target": "< 60 s",
        "action_threshold": "> 120 s",
        "unit": "s",
        "source": "ALM-PHIL-001 section 8",
    },
    {
        "kpi": "recurring_rate",
        "description": "Share of alarms that repeat the same asset+code within 7 days",
        "formula": "repeats / alarm_count",
        "target": "< 0.2",
        "action_threshold": ">= 0.3",
        "unit": "ratio",
        "source": "ALM-PHIL-001 section 8",
    },
    {
        "kpi": "suppression_candidate_rate",
        "description": "Share of alarms shorter than 2 minutes that cleared without acknowledgement",
        "formula": "short_unacknowledged / alarm_count",
        "target": "< 0.05",
        "action_threshold": ">= 0.1",
        "unit": "ratio",
        "source": "ALM-PHIL-001 section 8",
    },
]

_CODE_TEMPLATES = {
    "alarm_flood_index": """
        alarms = query_alarms(scope, start_time, end_time).sort_by("start_time")
        floods = rolling_windows(alarms, minutes=10).where(count > 10).merge_overlapping()
        value = 100 * sum(f.duration for f in floods) / (end_time - start_time)
    """,
    "critical_alarm_density": """
        alarms = query_alarms(scope, start_time, end_time)
        value = 100 * count(a for a in alarms if a.severity == "critical") / len(alarms)
    """,
    "operator_response_efficiency": """
        acked = [a for a in query_alarms(scope, start_time, end_time) if a.ack_time]
        on_time = [a for a in acked if a.ack_delay <= MAX_RESPONSE[a.severity]]
        value = 100 * len(on_time) / len(acked)
    """,
    "nuisance_alarm_score": """
        alarms = query_alarms(scope, start_time, end_time)
        short = count(a for a in alarms if a.duration < 2 min and not a.ack_time)
        chatter = chatter_activations(alarms, threshold=3, window=1 min)
        value = min(100, 100 * (short + chatter) / len(alarms))
    """,
    "average_alarm_rate": """
        alarms = query_alarms(scope, start_time, end_time)
        value = len(alarms) / ((end_time - start_time).minutes / 10)
    """,
}


class CalculationEngine:
    def __init__(self, repo: Repository, analytics: Analytics) -> None:
        self.repo = repo
        self.analytics = analytics
        self._store: dict[str, dict[str, Any]] = {}

    def generate(self, calculation_type: str, filters: CalculationFilters) -> dict[str, Any]:
        calc_id = f"CALC-{uuid.uuid4().hex[:10].upper()}"
        record = {
            "calculation_id": calc_id,
            "calculation_type": calculation_type,
            "language": "pseudo-python",
            "code": textwrap.dedent(_CODE_TEMPLATES[calculation_type]).strip(),
            "description": next((k["description"] for k in KPI_DEFINITIONS if k["kpi"] == calculation_type), ""),
            "filters": filters.model_dump(mode="json"),
            "created_at": iso(datetime.now(self.repo.anchor.tzinfo)),
            "executable": True,
        }
        self._store[calc_id] = record
        return record

    def execute(self, calculation_id: str, filters: CalculationFilters | None) -> dict[str, Any]:
        record = self._store.get(calculation_id)
        if record is None:
            raise NotFoundError("calculation", calculation_id)
        f = filters or CalculationFilters.model_validate(record["filters"])
        alarms = self.repo.filter_alarms(asset_ids=f.asset_ids, site=f.site, unit=f.unit, start=f.start_time, end=f.end_time)
        n = len(alarms)
        ctype = record["calculation_type"]
        breakdown: dict[str, Any] = {"alarm_count": n}

        if ctype == "alarm_flood_index":
            flood = self.analytics.flood_analysis(
                FloodAnalysisRequest(
                    asset_ids=f.asset_ids, site=f.site, unit=f.unit, time_range=TimeRange(start_time=f.start_time, end_time=f.end_time)
                )
            )
            value, unit = flood["percent_time_in_flood"], "%"
            breakdown |= {
                "flood_count": flood["flood_count"],
                "flood_windows": [{k: w[k] for k in ("start", "end", "alarm_count")} for w in flood["flood_windows"]],
            }
        elif ctype == "critical_alarm_density":
            critical = sum(ALARM_DEFINITIONS[a.alarm_code].severity == "critical" for a in alarms)
            value, unit = (round(100 * critical / n, 2) if n else 0.0), "%"
            breakdown["critical_count"] = critical
        elif ctype == "operator_response_efficiency":
            acked = [a for a in alarms if a.ack_time]
            on_time = [
                a
                for a in acked
                if ((a.ack_time or a.start_time) - a.start_time).total_seconds()
                <= 60 * MAX_RESPONSE_MINUTES[ALARM_DEFINITIONS[a.alarm_code].severity]
            ]
            value, unit = (round(100 * len(on_time) / len(acked), 2) if acked else 0.0), "%"
            breakdown |= {
                "acknowledged": len(acked),
                "acknowledged_on_time": len(on_time),
                **self.analytics.kpis(alarms, ["avg_ack_delay", "unacknowledged_rate"]),
            }
        elif ctype == "nuisance_alarm_score":
            short = sum(self.analytics._is_suppression_candidate(a) for a in alarms)
            rat = self.analytics.rationalization(_rationalization_request(f))
            chatter = sum(c["chatter_events"] for c in rat["candidates"])
            value, unit = (round(min(100.0, 100 * (short + chatter) / n), 1) if n else 0.0), "score"
            breakdown |= {
                "short_unacknowledged": short,
                "chattering_activations": chatter,
                "top_nuisance_alarms": [
                    {k: c[k] for k in ("asset_id", "alarm_code", "occurrences", "reasons")} for c in rat["candidates"][:5]
                ],
            }
        else:  # average_alarm_rate
            minutes = (f.end_time - f.start_time).total_seconds() / 60
            value, unit = round(n / (minutes / 10), 4), "alarms/10 min"

        definition = next(k for k in KPI_DEFINITIONS if k["kpi"] == ctype)
        return {
            "calculation_id": calculation_id,
            "calculation_type": ctype,
            "filters": f.model_dump(mode="json"),
            "result": {
                "value": value,
                "unit": unit,
                "target": definition["target"],
                "action_threshold": definition["action_threshold"],
                "breakdown": breakdown,
            },
            "executed_at": iso(datetime.now(self.repo.anchor.tzinfo)),
        }


def _rationalization_request(f: CalculationFilters):
    from alarm_api_sim.schemas import RationalizationRequest

    return RationalizationRequest(
        asset_ids=f.asset_ids, site=f.site, unit=f.unit, time_range=TimeRange(start_time=f.start_time, end_time=f.end_time)
    )
