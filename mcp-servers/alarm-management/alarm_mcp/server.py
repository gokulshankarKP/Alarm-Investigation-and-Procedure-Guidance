"""Alarm Management MCP server.

Exposes Alarm Management API operations as typed, read-only MCP tools:

    search_assets, get_asset_metadata, get_alarms, get_alarm_details, summarize_alarms,
    get_alarm_trends, correlate_alarms, analyze_alarm_floods, find_rationalization_candidates,
    score_alarm_priority, get_operator_recommendations, calculate_alarm_kpi, list_kpi_definitions

Cross-cutting behaviour:
* Inputs are validated from the typed signatures (pydantic) plus semantic checks
  (time-range order, scope required) -> ``INVALID_ARGUMENT`` tool errors.
* Outputs are validated against ``alarm_mcp.models`` -> ``UPSTREAM_CONTRACT_ERROR``.
* Upstream failures are mapped to JSON tool errors with a stable ``code``, ``retryable``
  flag, attempt count and ``trace_id``.
* Trace metadata: the client's ``x-trace-id`` / ``x-conversation-id`` HTTP headers are
  forwarded to the API as ``trace_id`` / ``x-metadata-tag``; one is generated if absent.
* The Alarm API token lives only inside this server; MCP clients authenticate with a
  separate bearer token (see ``auth.py``).
"""

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, TypeVar

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from alarm_mcp.config import McpServerSettings
from alarm_mcp.models import (
    AlarmDetailOutput,
    AlarmListOutput,
    AlarmSummaryOutput,
    AlarmTrendsOutput,
    AssetMetadataOutput,
    AssetSearchOutput,
    CorrelationOutput,
    FloodAnalysisOutput,
    KpiCalculationOutput,
    KpiDefinitionsOutput,
    PriorityScoreOutput,
    RationalizationOutput,
    RecommendationsOutput,
    ToolMeta,
)
from connectors.alarm_api import AlarmApiClient, AlarmApiError, ApiResult, RequestContext
from shared.observability import conversation_id_var, log_event, new_trace_id, trace_id_var

logger = logging.getLogger("alarm_mcp")

ModelT = TypeVar("ModelT", bound=BaseModel)
SERVER_NAME = "alarm-management"
INSTRUCTIONS = (
    "Read-only tools over the plant Alarm Management API. Typical chain: search_assets -> "
    "get_asset_metadata / get_alarms -> summarize_alarms / correlate_alarms / score_alarm_priority -> "
    "get_operator_recommendations. Times are ISO-8601 UTC. Tool errors are JSON objects with an "
    "'error.code' such as NOT_FOUND, INVALID_ARGUMENT, UPSTREAM_UNAVAILABLE or UPSTREAM_TIMEOUT."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
MAX_RANGE = timedelta(days=400)
_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"

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

AssetIds = Annotated[
    list[Annotated[str, Field(pattern=_ID)]] | None, Field(default=None, max_length=20, description="Asset identifiers, e.g. ['BFP-101']")
]
Site = Annotated[str | None, Field(default=None, max_length=64, description="Site, e.g. 'NorthPlant'")]
Unit = Annotated[str | None, Field(default=None, max_length=64, description="Unit, e.g. 'Unit 1'")]
StartTime = Annotated[datetime, Field(description="Window start, ISO-8601 UTC")]
EndTime = Annotated[datetime, Field(description="Window end (exclusive), ISO-8601 UTC")]
AlarmId = Annotated[str, Field(pattern=_ID, description="Alarm identifier, e.g. 'ALM-000612'")]


def tool_error(code: str, message: str, **extra: Any) -> ToolError:
    return ToolError(json.dumps({"error": {"code": code, "message": message, **extra}}, default=str))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z") if value.tzinfo else value.isoformat() + "Z"


def _check_range(start: datetime, end: datetime) -> None:
    if start >= end:
        raise tool_error("INVALID_ARGUMENT", "start_time must be before end_time")
    if end - start > MAX_RANGE:
        raise tool_error("INVALID_ARGUMENT", f"time range must not exceed {MAX_RANGE.days} days")


def _scope(asset_ids: list[str] | None, site: str | None, unit: str | None) -> dict[str, Any]:
    return {k: v for k, v in {"asset_ids": asset_ids, "site": site, "unit": unit}.items() if v}


class _Call:
    """One tool invocation: API client, trace context and collected upstream call metadata."""

    def __init__(self, tool: str, client: AlarmApiClient, ctx: RequestContext) -> None:
        self.tool = tool
        self.client = client
        self.ctx = ctx
        self.results: list[ApiResult] = []
        self.started = time.perf_counter()

    def record(self, result: ApiResult) -> dict[str, Any]:
        self.results.append(result)
        return result.data

    def meta(self) -> ToolMeta:
        return ToolMeta(
            trace_id=self.ctx.trace_id,
            tool=self.tool,
            api_calls=[r.meta() for r in self.results],
            total_duration_ms=round((time.perf_counter() - self.started) * 1000, 1),
        )

    def build(self, model: type[ModelT], data: dict[str, Any]) -> ModelT:
        payload = {k: v for k, v in data.items() if k != "meta"}
        try:
            return model.model_validate({**payload, "meta": self.meta()})
        except ValidationError as exc:
            raise tool_error(
                "UPSTREAM_CONTRACT_ERROR",
                f"Alarm API response did not match the {model.__name__} contract",
                details=[f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]],
                trace_id=self.ctx.trace_id,
                tool=self.tool,
            ) from None


def _incoming_headers(ctx: Context | None) -> dict[str, str]:
    try:
        request = ctx.request_context.request if ctx is not None else None
    except (ValueError, LookupError, AttributeError):
        request = None
    return dict(request.headers) if isinstance(request, Request) else {}


def create_server(
    settings: McpServerSettings | None = None,
    *,
    api_transport: httpx.AsyncBaseTransport | None = None,
) -> FastMCP:
    """Build the server. ``api_transport`` lets tests route API calls to an in-process app."""
    settings = settings or McpServerSettings()
    mcp = FastMCP(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[h.strip() for h in settings.allowed_hosts.split(",") if h.strip()],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    @asynccontextmanager
    async def invocation(tool: str, ctx: Context | None):
        headers = _incoming_headers(ctx)
        trace_id = headers.get("x-trace-id") or new_trace_id("mcp")
        conversation_id = headers.get("x-conversation-id")
        t_token = trace_id_var.set(trace_id)
        c_token = conversation_id_var.set(conversation_id)
        tag = f"mcp-tool:{tool}" + (f";conversation:{conversation_id}" if conversation_id else "")
        client = AlarmApiClient(
            settings.alarm_api_base_url,
            settings.alarm_api_token.get_secret_value(),
            timeout_s=settings.alarm_api_timeout_s,
            max_retries=settings.alarm_api_max_retries,
            backoff_base_s=settings.alarm_api_backoff_s,
            transport=api_transport,
        )
        call = _Call(tool, client, RequestContext(trace_id=trace_id, client_id="alarm-mcp-server", metadata_tag=tag))
        outcome = "success"
        try:
            yield call
        except AlarmApiError as exc:
            outcome = exc.code
            raise tool_error(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                retryable=exc.retryable,
                attempts=exc.attempts,
                trace_id=trace_id,
                tool=tool,
                endpoint=exc.endpoint,
                details=exc.details,
            ) from None
        except ToolError as exc:
            outcome = "tool_error"
            raise exc
        finally:
            await client.aclose()
            log_event(
                logger,
                "mcp_tool_call",
                tool=tool,
                outcome=outcome,
                duration_ms=round((time.perf_counter() - call.started) * 1000, 1),
                api_calls=len(call.results),
                retries=sum(len(r.retries) for r in call.results),
            )
            trace_id_var.reset(t_token)
            conversation_id_var.reset(c_token)

    # -- assets ----------------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    async def search_assets(
        query: Annotated[
            str,
            Field(
                min_length=2, max_length=200, description="Asset name, tag or class, e.g. 'Boiler Feed Pump 101', 'BFP-101', 'compressor'"
            ),
        ],
        site: Site = None,
        unit: Unit = None,
        asset_class: Annotated[
            str | None, Field(default=None, max_length=64, description="e.g. 'boiler_feed_pump', 'compressor', 'motor'")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        ctx: Context = None,
    ) -> AssetSearchOutput:
        """Resolve a free-text asset name or tag to asset identifiers (ranked matches with match_score 0-1). Use this first to turn names like 'Boiler Feed Pump 101' into asset_id values."""
        async with invocation("search_assets", ctx) as call:
            data = call.record(await call.client.search_assets(call.ctx, query, limit=limit, site=site, unit=unit, asset_class=asset_class))
            return call.build(AssetSearchOutput, data)

    @mcp.tool(annotations=READ_ONLY)
    async def get_asset_metadata(
        asset_id: Annotated[str, Field(pattern=_ID, description="Asset identifier from search_assets, e.g. 'BFP-101'")],
        ctx: Context = None,
    ) -> AssetMetadataOutput:
        """Get asset master data: class, site/unit, criticality (A/B/C), attributes, maintenance info and RELATED ASSETS (driver motor, upstream/downstream equipment, standby units) with their relationship."""
        async with invocation("get_asset_metadata", ctx) as call:
            return call.build(AssetMetadataOutput, call.record(await call.client.asset_metadata(call.ctx, asset_id)))

    # -- alarms ----------------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    async def get_alarms(
        asset_ids: AssetIds = None,
        site: Site = None,
        unit: Unit = None,
        status: Literal["active", "cleared", "all"] = "all",
        severities: Annotated[list[Severity] | None, Field(default=None, description="Filter by severity")] = None,
        alarm_code: Annotated[str | None, Field(default=None, pattern=_ID)] = None,
        start_time: Annotated[datetime | None, Field(default=None, description="Only alarms starting at/after this time")] = None,
        end_time: Annotated[datetime | None, Field(default=None, description="Only alarms starting before this time")] = None,
        sort_by: Literal["start_time", "severity", "priority", "duration"] = "start_time",
        sort_order: Literal["asc", "desc"] = "desc",
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=200)] = 50,
        fetch_all_pages: Annotated[bool, Field(description=f"Follow pagination (max {settings.max_pages} pages)")] = False,
        ctx: Context = None,
    ) -> AlarmListOutput:
        """Retrieve active or historical alarms with filters and pagination. At least one of asset_ids, site, unit or alarm_code is required. Use status='active' for current alarms."""
        if not (asset_ids or site or unit or alarm_code):
            raise tool_error("INVALID_ARGUMENT", "Provide at least one of asset_ids, site, unit or alarm_code")
        if start_time and end_time:
            _check_range(start_time, end_time)
        async with invocation("get_alarms", ctx) as call:
            params = {
                "asset_id": ",".join(asset_ids) if asset_ids else None,
                "site": site,
                "unit": unit,
                "status": status,
                "severity": ",".join(severities) if severities else None,
                "alarm_code": alarm_code,
                "start_time": _iso(start_time),
                "end_time": _iso(end_time),
                "sort_by": sort_by,
                "sort_order": sort_order,
                "page_size": page_size,
                "page": page,
            }
            if fetch_all_pages:
                rows, pagination, results = await call.client.list_all_alarms(call.ctx, max_pages=settings.max_pages, **params)
                for r in results:
                    call.record(r)
                pages = len(results)
            else:
                data = call.record(await call.client.list_alarms(call.ctx, **params))
                rows, pagination, pages = data.get("data"), data.get("pagination"), 1
            return call.build(
                AlarmListOutput,
                {
                    "alarms": rows,
                    "pagination": pagination,
                    "pages_fetched": pages,
                    "truncated": bool((pagination or {}).get("has_next")),
                },
            )

    @mcp.tool(annotations=READ_ONLY)
    async def get_alarm_details(alarm_id: AlarmId, ctx: Context = None) -> AlarmDetailOutput:
        """Get one alarm by id (state, acknowledgement, duration, value vs setpoint)."""
        async with invocation("get_alarm_details", ctx) as call:
            return call.build(AlarmDetailOutput, {"alarm": call.record(await call.client.get_alarm(call.ctx, alarm_id))})

    @mcp.tool(annotations=READ_ONLY)
    async def summarize_alarms(
        start_time: StartTime,
        end_time: EndTime,
        asset_ids: AssetIds = None,
        site: Site = None,
        unit: Unit = None,
        severities: Annotated[list[Severity] | None, Field(default=None)] = None,
        alarm_types: Annotated[list[AlarmType] | None, Field(default=None)] = None,
        group_by: Annotated[list[GroupBy], Field(max_length=4)] = ["alarm_name"],  # noqa: B006
        kpis: Annotated[list[SummaryKpi], Field(min_length=1)] = ["alarm_count", "recurring_rate", "avg_ack_delay"],  # noqa: B006
        ctx: Context = None,
    ) -> AlarmSummaryOutput:
        """Aggregate alarms over a time window: totals and per-group KPIs (alarm_count, recurring_rate, avg_ack_delay, critical_count, ...) plus the top recurring alarms."""
        _check_range(start_time, end_time)
        async with invocation("summarize_alarms", ctx) as call:
            body = {
                **_scope(asset_ids, site, unit),
                "time_range": {"start_time": _iso(start_time), "end_time": _iso(end_time)},
                "group_by": group_by,
                "kpis": kpis,
            }
            if severities:
                body["severity"] = severities
            if alarm_types:
                body["alarm_types"] = alarm_types
            return call.build(AlarmSummaryOutput, call.record(await call.client.alarm_summary(call.ctx, body)))

    @mcp.tool(annotations=READ_ONLY)
    async def get_alarm_trends(
        start_time: StartTime,
        end_time: EndTime,
        asset_ids: AssetIds = None,
        site: Site = None,
        unit: Unit = None,
        bucket: Literal["hourly", "daily", "weekly"] = "weekly",
        metrics: Annotated[list[TrendMetric], Field(min_length=1)] = ["alarm_count"],  # noqa: B006
        ctx: Context = None,
    ) -> AlarmTrendsOutput:
        """Time-bucketed alarm metrics with a trend direction (increasing / stable / decreasing) per metric."""
        _check_range(start_time, end_time)
        async with invocation("get_alarm_trends", ctx) as call:
            body = {
                **_scope(asset_ids, site, unit),
                "time_range": {"start_time": _iso(start_time), "end_time": _iso(end_time)},
                "bucket": bucket,
                "metrics": metrics,
            }
            return call.build(AlarmTrendsOutput, call.record(await call.client.alarm_trends(call.ctx, body)))

    @mcp.tool(annotations=READ_ONLY)
    async def correlate_alarms(
        asset_ids: Annotated[list[Annotated[str, Field(pattern=_ID)]], Field(min_length=1, max_length=20)],
        start_time: StartTime,
        end_time: EndTime,
        lag_window_minutes: Annotated[int, Field(ge=1, le=1440)] = 15,
        severity_threshold: Severity = "medium",
        min_support: Annotated[int, Field(ge=1)] = 2,
        include_related: Annotated[bool, Field(description="Also analyse alarms on related assets (deaerator, valves, supply)")] = True,
        ctx: Context = None,
    ) -> CorrelationOutput:
        """Find alarm sequences that co-occur within a lag window (antecedent -> consequent, support, confidence) and common-cause candidate assets. Use to explain WHY alarms recur and WHICH related assets to inspect."""
        _check_range(start_time, end_time)
        async with invocation("correlate_alarms", ctx) as call:
            body = {
                "asset_ids": asset_ids,
                "time_range": {"start_time": _iso(start_time), "end_time": _iso(end_time)},
                "correlation_method": "cooccurrence",
                "lag_window_minutes": lag_window_minutes,
                "severity_threshold": severity_threshold,
                "min_support": min_support,
                "include_related": include_related,
            }
            return call.build(CorrelationOutput, call.record(await call.client.alarm_correlation(call.ctx, body)))

    @mcp.tool(annotations=READ_ONLY)
    async def analyze_alarm_floods(
        start_time: StartTime,
        end_time: EndTime,
        site: Site = None,
        unit: Unit = None,
        asset_ids: AssetIds = None,
        threshold_count: Annotated[int, Field(ge=2, le=1000)] = 10,
        rolling_window_minutes: Annotated[int, Field(ge=1, le=1440)] = 10,
        ctx: Context = None,
    ) -> FloodAnalysisOutput:
        """Detect alarm floods (more than threshold_count alarms in a rolling window) with initiating alarm and percent time in flood."""
        _check_range(start_time, end_time)
        if not (site or unit or asset_ids):
            raise tool_error("INVALID_ARGUMENT", "Provide site, unit or asset_ids")
        async with invocation("analyze_alarm_floods", ctx) as call:
            body = {
                **_scope(asset_ids, site, unit),
                "time_range": {"start_time": _iso(start_time), "end_time": _iso(end_time)},
                "threshold_count": threshold_count,
                "rolling_window_minutes": rolling_window_minutes,
            }
            return call.build(FloodAnalysisOutput, call.record(await call.client.flood_analysis(call.ctx, body)))

    @mcp.tool(annotations=READ_ONLY)
    async def find_rationalization_candidates(
        start_time: StartTime,
        end_time: EndTime,
        asset_ids: AssetIds = None,
        site: Site = None,
        unit: Unit = None,
        recurrence_threshold: Annotated[int, Field(ge=1, description="Occurrences within 7 days")] = 5,
        stale_minutes_threshold: Annotated[int, Field(ge=1)] = 180,
        ctx: Context = None,
    ) -> RationalizationOutput:
        """List alarms that should be rationalized: recurring, chattering, stale, or cleared without operator action."""
        _check_range(start_time, end_time)
        async with invocation("find_rationalization_candidates", ctx) as call:
            body = {
                **_scope(asset_ids, site, unit),
                "time_range": {"start_time": _iso(start_time), "end_time": _iso(end_time)},
                "recurrence_threshold": recurrence_threshold,
                "stale_minutes_threshold": stale_minutes_threshold,
            }
            return call.build(RationalizationOutput, call.record(await call.client.rationalization_candidates(call.ctx, body)))

    @mcp.tool(annotations=READ_ONLY)
    async def score_alarm_priority(alarm_id: AlarmId, ctx: Context = None) -> PriorityScoreOutput:
        """Dynamic 0-100 priority score for one alarm with component breakdown (severity, asset criticality, time unacknowledged, recurrence, related alarms)."""
        async with invocation("score_alarm_priority", ctx) as call:
            return call.build(PriorityScoreOutput, call.record(await call.client.priority_score(call.ctx, alarm_id)))

    @mcp.tool(annotations=READ_ONLY)
    async def get_operator_recommendations(
        alarm_id: AlarmId,
        include_related: bool = True,
        include_asset_context: bool = True,
        include_historical_pattern: bool = True,
        ctx: Context = None,
    ) -> RecommendationsOutput:
        """System-generated operator actions for an alarm, with related alarms and historical pattern. These recommendations are NOT authoritative: verify them against site procedures."""
        async with invocation("get_operator_recommendations", ctx) as call:
            body = {
                "alarm_id": alarm_id,
                "include_related": include_related,
                "include_asset_context": include_asset_context,
                "include_historical_pattern": include_historical_pattern,
            }
            return call.build(RecommendationsOutput, call.record(await call.client.operator_recommendations(call.ctx, body)))

    # -- KPIs ------------------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    async def calculate_alarm_kpi(
        calculation_type: CalculationType,
        start_time: StartTime,
        end_time: EndTime,
        site: Site = None,
        unit: Unit = None,
        asset_ids: AssetIds = None,
        ctx: Context = None,
    ) -> KpiCalculationOutput:
        """Compute an alarm-management KPI (flood index, critical density, response efficiency, nuisance score, average rate). Chains calculation-code/generate -> calculation-code/execute."""
        _check_range(start_time, end_time)
        async with invocation("calculate_alarm_kpi", ctx) as call:
            filters = {**_scope(asset_ids, site, unit), "start_time": _iso(start_time), "end_time": _iso(end_time)}
            generated = call.record(
                await call.client.generate_calculation(call.ctx, {"calculation_type": calculation_type, "filters": filters})
            )
            calc_id = generated.get("calculation_id")
            if not isinstance(calc_id, str) or not re.match(_ID, calc_id):
                raise tool_error(
                    "UPSTREAM_CONTRACT_ERROR",
                    "calculation-code/generate returned no valid calculation_id",
                    trace_id=call.ctx.trace_id,
                    tool="calculate_alarm_kpi",
                )
            executed = call.record(await call.client.execute_calculation(call.ctx, {"calculation_id": calc_id, "filters": filters}))
            return call.build(KpiCalculationOutput, {**executed, "code": generated.get("code", "")})

    @mcp.tool(annotations=READ_ONLY)
    async def list_kpi_definitions(ctx: Context = None) -> KpiDefinitionsOutput:
        """List alarm-management KPI definitions with formulas and targets."""
        async with invocation("list_kpi_definitions", ctx) as call:
            return call.build(KpiDefinitionsOutput, call.record(await call.client.kpi_definitions(call.ctx)))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "tools": len(await mcp.list_tools())})

    return mcp
