"""Request models. Field names and shapes follow the Postman collections exactly."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["low", "medium", "high", "critical"]
AlarmType = Literal["process", "device", "safety", "system"]
GroupBy = Literal["alarm_name", "alarm_code", "asset_id", "asset_name", "asset_class", "severity", "alarm_type", "site", "unit", "status"]
SummaryKpi = Literal[
    "alarm_count",
    "critical_count",
    "high_count",
    "active_count",
    "recurring_rate",
    "avg_ack_delay",
    "avg_duration",
    "unacknowledged_rate",
    "suppression_candidate_rate",
]
TrendMetric = Literal["alarm_count", "avg_ack_delay", "critical_count", "avg_duration"]
CalculationType = Literal[
    "alarm_flood_index", "critical_alarm_density", "operator_response_efficiency", "nuisance_alarm_score", "average_alarm_rate"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeRange(_Strict):
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def _ordered(self) -> TimeRange:
        if self.start_time >= self.end_time:
            raise ValueError("time_range.start_time must be before time_range.end_time")
        return self


class Scope(_Strict):
    asset_ids: list[str] | None = Field(default=None, max_length=50)
    site: str | None = None
    unit: str | None = None


class SummaryRequest(Scope):
    time_range: TimeRange
    severity: list[Severity] | None = None
    alarm_types: list[AlarmType] | None = None
    group_by: list[GroupBy] = Field(default_factory=list, max_length=4)
    kpis: list[SummaryKpi] = Field(default_factory=lambda: list[SummaryKpi](["alarm_count"]), min_length=1)


class TrendsRequest(Scope):
    time_range: TimeRange
    bucket: Literal["hourly", "daily", "weekly"] = "daily"
    metrics: list[TrendMetric] = Field(default_factory=lambda: list[TrendMetric](["alarm_count"]), min_length=1)
    severity: list[Severity] | None = None


class CorrelationRequest(_Strict):
    asset_ids: list[str] = Field(min_length=1, max_length=20)
    time_range: TimeRange
    correlation_method: Literal["cooccurrence"] = "cooccurrence"
    lag_window_minutes: int = Field(default=15, ge=1, le=1440)
    severity_threshold: Severity = "low"
    min_support: int = Field(default=1, ge=1)
    include_related: bool = True


class FloodAnalysisRequest(Scope):
    time_range: TimeRange
    threshold_count: int = Field(default=10, ge=2, le=1000)
    rolling_window_minutes: int = Field(default=10, ge=1, le=1440)


class RationalizationRequest(Scope):
    time_range: TimeRange
    recurrence_threshold: int = Field(default=5, ge=1)
    stale_minutes_threshold: int = Field(default=180, ge=1)
    chatter_threshold: int = Field(default=3, ge=2)
    chatter_window_minutes: float = Field(default=1.0, gt=0)


class PriorityScoreRequest(_Strict):
    alarm_id: str = Field(min_length=1)


class RecommendationRequest(_Strict):
    alarm_id: str = Field(min_length=1)
    include_related: bool = False
    include_asset_context: bool = False
    include_historical_pattern: bool = False


class CalculationFilters(Scope):
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def _ordered(self) -> CalculationFilters:
        if self.start_time >= self.end_time:
            raise ValueError("filters.start_time must be before filters.end_time")
        return self


class CalculationGenerateRequest(_Strict):
    calculation_type: CalculationType
    filters: CalculationFilters


class CalculationExecuteRequest(_Strict):
    calculation_id: str = Field(min_length=1)
    filters: CalculationFilters | None = None


class FaultRule(_Strict):
    path_prefix: str = Field(min_length=1)
    mode: Literal["error", "timeout", "rate_limit"] = "error"
    status_code: int = Field(default=503, ge=400, le=599)
    count: int = Field(default=1, ge=1, le=1000)
    delay_seconds: float = Field(default=30.0, ge=0, le=300)
