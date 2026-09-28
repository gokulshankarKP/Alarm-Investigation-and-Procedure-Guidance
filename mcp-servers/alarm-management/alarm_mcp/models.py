"""Typed MCP tool output contracts.

Upstream API responses are validated against these models before being returned
(output validation); a mismatch becomes an ``UPSTREAM_CONTRACT_ERROR`` tool error.
Models allow extra fields so additive API changes do not break the tools.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["low", "medium", "high", "critical"]


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class ToolMeta(BaseModel):
    """Execution metadata attached to every tool result (shown in the copilot trace)."""

    trace_id: str
    tool: str
    api_calls: list[dict[str, Any]] = Field(
        default_factory=list, description="Upstream calls: endpoint, status, attempts, retries, duration"
    )
    total_duration_ms: float = 0.0


class AssetMatch(_Open):
    asset_id: str
    asset_name: str
    asset_class: str
    site: str
    unit: str
    criticality: str
    match_score: float
    exact_match: bool = False


class AssetSearchOutput(BaseModel):
    query: str
    results: list[AssetMatch]
    total: int
    meta: ToolMeta


class RelatedAsset(_Open):
    asset_id: str
    asset_name: str
    asset_class: str
    relationship: str
    criticality: str


class AssetMetadataOutput(_Open):
    asset_id: str
    asset_name: str
    asset_class: str
    site: str
    unit: str
    criticality: str
    description: str
    related_assets: list[RelatedAsset]
    attributes: dict[str, str] = Field(default_factory=dict)
    alarm_statistics: dict[str, Any] = Field(default_factory=dict)
    maintenance: dict[str, Any] = Field(default_factory=dict)
    meta: ToolMeta


class Alarm(_Open):
    alarm_id: str
    asset_id: str
    asset_name: str
    site: str
    unit: str
    alarm_code: str
    alarm_name: str
    alarm_type: str
    severity: Severity
    priority: int
    status: Literal["active", "cleared"]
    acknowledged: bool
    start_time: str
    end_time: str | None = None
    ack_time: str | None = None
    duration_minutes: float
    ack_delay_seconds: float | None = None
    value: float | None = None
    setpoint: float | None = None
    uom: str | None = None
    is_trip: bool = False


class Pagination(_Open):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool


class AlarmListOutput(BaseModel):
    alarms: list[Alarm]
    pagination: Pagination
    pages_fetched: int
    truncated: bool = Field(description="True when more pages exist than were fetched")
    meta: ToolMeta


class AlarmDetailOutput(BaseModel):
    alarm: Alarm
    meta: ToolMeta


class AlarmSummaryOutput(_Open):
    totals: dict[str, Any]
    groups: list[dict[str, Any]]
    top_alarms: list[dict[str, Any]]
    meta: ToolMeta


class TrendDirection(_Open):
    direction: Literal["increasing", "decreasing", "stable"]
    first_half_avg: float
    second_half_avg: float
    relative_change: float


class AlarmTrendsOutput(_Open):
    bucket: str
    series: list[dict[str, Any]]
    trend: dict[str, TrendDirection]
    total_alarms: int
    meta: ToolMeta


class AlarmKey(_Open):
    asset_id: str
    alarm_code: str


class CorrelationPair(_Open):
    antecedent: AlarmKey
    consequent: AlarmKey
    support: int
    confidence: float
    median_lag_minutes: float
    cross_asset: bool


class CommonCause(_Open):
    asset_id: str
    asset_name: str
    affected_assets: list[str]
    evidence: int


class CorrelationOutput(_Open):
    assets_analyzed: list[str]
    alarms_analyzed: int
    pairs: list[CorrelationPair]
    common_cause_candidates: list[CommonCause]
    insights: list[str]
    meta: ToolMeta


class FloodWindow(_Open):
    start: str
    end: str
    alarm_count: int
    assets_involved: list[str]
    top_alarm_codes: list[str]


class FloodAnalysisOutput(_Open):
    total_alarms: int
    flood_count: int
    percent_time_in_flood: float
    flood_windows: list[FloodWindow]
    meta: ToolMeta


class RationalizationCandidate(_Open):
    asset_id: str
    alarm_code: str
    alarm_name: str
    reasons: list[str]
    occurrences: int
    max_occurrences_in_7_days: int
    suggested_review: str


class RationalizationOutput(_Open):
    candidate_count: int
    candidates: list[RationalizationCandidate]
    criteria: dict[str, Any]
    meta: ToolMeta


class PriorityComponent(_Open):
    factor: str
    weight_pct: int
    points: float
    detail: str


class PriorityScoreOutput(_Open):
    alarm_id: str
    asset_id: str
    alarm_code: str
    severity: Severity
    configured_priority: int
    priority_score: float
    priority_band: str
    components: list[PriorityComponent]
    rationale: str
    meta: ToolMeta


class Recommendation(_Open):
    rank: int
    action: str
    rationale: str
    confidence: float
    source: str


class RecommendationsOutput(_Open):
    alarm_id: str
    asset_id: str
    alarm_code: str
    recommendations: list[Recommendation]
    related_alarms: list[Alarm] = Field(default_factory=list)
    asset_context: dict[str, Any] | None = None
    historical_pattern: dict[str, Any] | None = None
    disclaimer: str | None = None
    meta: ToolMeta


class KpiResult(_Open):
    value: float
    unit: str
    target: str
    action_threshold: str
    breakdown: dict[str, Any]


class KpiCalculationOutput(_Open):
    calculation_id: str
    calculation_type: str
    code: str
    result: KpiResult
    meta: ToolMeta


class KpiDefinition(_Open):
    kpi: str
    description: str
    formula: str
    target: str


class KpiDefinitionsOutput(BaseModel):
    kpis: list[KpiDefinition]
    meta: ToolMeta
