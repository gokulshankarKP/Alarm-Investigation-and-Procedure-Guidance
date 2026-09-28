"""FastAPI application for the Alarm Management API simulator.

Contract: ``agent_api_and_complete_flow/postman`` (15 endpoints, bearer auth, trace headers
``trace_id`` / ``x-client-id`` / ``x-metadata-tag``, page/page_size pagination).

Run: ``python -m alarm_api_sim`` or ``uvicorn alarm_api_sim.main:build_app --factory --port 8000``.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from alarm_api_sim.analytics import Analytics
from alarm_api_sim.calculations import KPI_DEFINITIONS, CalculationEngine
from alarm_api_sim.config import SimulatorSettings
from alarm_api_sim.recommendations import operator_recommendations
from alarm_api_sim.repository import NotFoundError, Repository, iso
from alarm_api_sim.schemas import (
    CalculationExecuteRequest,
    CalculationGenerateRequest,
    CorrelationRequest,
    FaultRule,
    FloodAnalysisRequest,
    PriorityScoreRequest,
    RationalizationRequest,
    RecommendationRequest,
    SummaryRequest,
    TrendsRequest,
)
from shared.observability import configure_logging, log_event, trace_id_var

logger = logging.getLogger("alarm_api_sim")
API_VERSION = "1.0.0"
MAX_PAGE_SIZE = 200


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def _error(
    request: Request, status: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}, "trace_id": trace_id},
        headers=headers,
    )


def create_app(settings: SimulatorSettings | None = None) -> FastAPI:
    settings = settings or SimulatorSettings()
    repo = Repository(settings.anchor_time, settings.seed)
    analytics = Analytics(repo)
    calculations = CalculationEngine(repo, analytics)
    faults: list[dict[str, Any]] = []
    request_log: deque[dict[str, Any]] = deque(maxlen=500)

    app = FastAPI(
        title="Alarm Management API (Simulator)",
        version=API_VERSION,
        description="Simulator implementing the Alarm Management API contract from the Postman collections.",
    )
    app.state.repo = repo
    app.state.request_log = request_log
    app.state.faults = faults

    # -- middleware: trace context, request log, fault injection -------------------------

    @app.middleware("http")
    async def trace_and_faults(request: Request, call_next):
        trace_id = request.headers.get("trace_id") or request.headers.get("x-trace-id") or f"sim-{uuid.uuid4().hex[:16]}"
        request.state.trace_id = trace_id
        request.state.request_id = f"req-{uuid.uuid4().hex[:12]}"
        token = trace_id_var.set(trace_id)
        started = time.perf_counter()
        try:
            response = None
            rule = next((f for f in faults if request.url.path.startswith(f["path_prefix"]) and f["remaining"] > 0), None)
            if rule is not None and not request.url.path.startswith("/admin"):
                rule["remaining"] -= 1
                if rule["mode"] == "timeout":
                    await asyncio.sleep(rule["delay_seconds"])
                elif rule["mode"] == "rate_limit":
                    response = _error(request, 429, "RATE_LIMITED", "Too many requests (injected fault)", headers={"Retry-After": "1"})
                else:
                    response = _error(request, rule["status_code"], "UPSTREAM_FAILURE", f"Injected fault on {request.url.path}")
            if response is None:
                response = await call_next(request)
            response.headers["trace_id"] = trace_id
            response.headers["x-trace-id"] = trace_id
            response.headers["x-request-id"] = request.state.request_id
            for header in ("x-client-id", "x-metadata-tag"):
                if value := request.headers.get(header):
                    response.headers[header] = value
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            entry: dict[str, Any] = {
                "ts": iso(datetime.now(UTC)),
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "trace_id": trace_id,
                "client_id": request.headers.get("x-client-id"),
                "metadata_tag": request.headers.get("x-metadata-tag"),
            }
            if not request.url.path.startswith("/admin"):
                request_log.append(entry)
            log_event(logger, "http_request", **{k: v for k, v in entry.items() if k != "ts"})
            return response
        finally:
            trace_id_var.reset(token)

    # -- error handlers ----------------------------------------------------------------------

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _error(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError):
        return _error(request, 404, "NOT_FOUND", str(exc), {"resource": exc.resource, "id": exc.identifier})

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _error(request, 422, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        return _error(request, 400, "BAD_REQUEST", str(exc))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log_event(logger, "unhandled_error", logging.ERROR, error=type(exc).__name__, path=request.url.path)
        return _error(request, 500, "INTERNAL_ERROR", "Unexpected server error")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return _error(request, exc.status_code, code, str(exc.detail))

    # -- auth ------------------------------------------------------------------------------

    expected = settings.api_token.get_secret_value()

    def require_auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise ApiError(401, "UNAUTHORIZED", "Missing bearer token")
        if not hmac.compare_digest(token.encode(), expected.encode()):
            raise ApiError(401, "UNAUTHORIZED", "Invalid bearer token")

    Auth = Depends(require_auth)

    def meta(request: Request) -> dict[str, Any]:
        return {
            "trace_id": request.state.trace_id,
            "request_id": request.state.request_id,
            "client_id": request.headers.get("x-client-id"),
            "metadata_tag": request.headers.get("x-metadata-tag"),
            "api_version": API_VERSION,
            "data_as_of": iso(repo.anchor),
            "generated_at": iso(datetime.now(UTC)),
        }

    # -- endpoints ------------------------------------------------------------------------

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "alarm-api-simulator",
            "version": API_VERSION,
            "alarms_loaded": len(repo.alarms),
            "data_as_of": iso(repo.anchor),
        }

    @app.get("/assets/search", tags=["assets"], dependencies=[Auth])
    async def search_assets(
        request: Request,
        query: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
        site: str | None = None,
        unit: str | None = None,
        asset_class: str | None = None,
    ) -> dict[str, Any]:
        results = repo.search_assets(query, site, unit, asset_class, limit)
        return {"query": query, "results": results, "total": len(results), "meta": meta(request)}

    @app.get("/assets/{asset_id}/metadata", tags=["assets"], dependencies=[Auth])
    async def asset_metadata(request: Request, asset_id: str) -> dict[str, Any]:
        return {**repo.asset_metadata(asset_id), "meta": meta(request)}

    @app.get("/alarms", tags=["alarms"], dependencies=[Auth])
    async def list_alarms(
        request: Request,
        asset_id: str | None = None,
        site: str | None = None,
        unit: str | None = None,
        status: Literal["active", "cleared", "all"] | None = None,
        severity: Annotated[str | None, Query(description="Comma-separated severities")] = None,
        alarm_code: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
        sort_by: Literal["start_time", "severity", "priority", "duration"] = "start_time",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> dict[str, Any]:
        severities = [s.strip() for s in severity.split(",")] if severity else None
        if severities and not set(severities) <= {"low", "medium", "high", "critical"}:
            raise ApiError(422, "VALIDATION_ERROR", "severity must be a comma-separated list of low|medium|high|critical")
        if start_time and end_time and start_time >= end_time:
            raise ApiError(422, "VALIDATION_ERROR", "start_time must be before end_time")
        asset_ids = [a.strip() for a in asset_id.split(",")] if asset_id else None
        rows = repo.filter_alarms(
            asset_ids=asset_ids,
            site=site,
            unit=unit,
            status=None if status == "all" else status,
            severities=severities,
            alarm_codes=[alarm_code] if alarm_code else None,
            start=start_time,
            end=end_time,
        )
        keys = {
            "start_time": lambda a: a.start_time,
            "severity": lambda a: (-repo.serialize(a)["priority"], a.start_time),
            "priority": lambda a: (-repo.serialize(a)["priority"], a.start_time),
            "duration": lambda a: repo.duration_minutes(a),
        }
        rows.sort(key=keys[sort_by], reverse=sort_order == "desc")
        total = len(rows)
        offset = (page - 1) * page_size
        return {
            "data": [repo.serialize(a) for a in rows[offset : offset + page_size]],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": (total + page_size - 1) // page_size,
                "has_next": offset + page_size < total,
            },
            "filters": {
                k: v
                for k, v in {
                    "asset_id": asset_id,
                    "site": site,
                    "unit": unit,
                    "status": status,
                    "severity": severity,
                    "alarm_code": alarm_code,
                    "start_time": iso(start_time),
                    "end_time": iso(end_time),
                    "sort_by": sort_by,
                    "sort_order": sort_order,
                }.items()
                if v is not None
            },
            "meta": meta(request),
        }

    @app.get("/alarms/{alarm_id}", tags=["alarms"], dependencies=[Auth])
    async def get_alarm(request: Request, alarm_id: str) -> dict[str, Any]:
        return {**repo.serialize(repo.alarm(alarm_id)), "meta": meta(request)}

    @app.post("/alarms/summary", tags=["analytics"], dependencies=[Auth])
    async def alarm_summary(request: Request, body: SummaryRequest) -> dict[str, Any]:
        return {"request": body.model_dump(mode="json", exclude_none=True), **analytics.summary(body), "meta": meta(request)}

    @app.post("/alarms/trends", tags=["analytics"], dependencies=[Auth])
    async def alarm_trends(request: Request, body: TrendsRequest) -> dict[str, Any]:
        return {"request": body.model_dump(mode="json", exclude_none=True), **analytics.trends(body), "meta": meta(request)}

    @app.post("/alarms/correlation", tags=["analytics"], dependencies=[Auth])
    async def alarm_correlation(request: Request, body: CorrelationRequest) -> dict[str, Any]:
        return {"request": body.model_dump(mode="json"), **analytics.correlation(body), "meta": meta(request)}

    @app.post("/alarms/flood-analysis", tags=["analytics"], dependencies=[Auth])
    async def flood_analysis(request: Request, body: FloodAnalysisRequest) -> dict[str, Any]:
        return {"request": body.model_dump(mode="json", exclude_none=True), **analytics.flood_analysis(body), "meta": meta(request)}

    @app.post("/alarms/rationalization-candidates", tags=["analytics"], dependencies=[Auth])
    async def rationalization(request: Request, body: RationalizationRequest) -> dict[str, Any]:
        return {"request": body.model_dump(mode="json", exclude_none=True), **analytics.rationalization(body), "meta": meta(request)}

    @app.post("/alarms/priority-score", tags=["analytics"], dependencies=[Auth])
    async def priority_score(request: Request, body: PriorityScoreRequest) -> dict[str, Any]:
        return {**analytics.priority_score(body.alarm_id), "meta": meta(request)}

    @app.post("/recommendations/operator-actions", tags=["recommendations"], dependencies=[Auth])
    async def recommendations(request: Request, body: RecommendationRequest) -> dict[str, Any]:
        result = operator_recommendations(
            repo, analytics, body.alarm_id, body.include_related, body.include_asset_context, body.include_historical_pattern
        )
        return {**result, "meta": meta(request)}

    @app.post("/calculation-code/generate", tags=["kpi"], dependencies=[Auth])
    async def generate_calculation(request: Request, body: CalculationGenerateRequest) -> dict[str, Any]:
        return {**calculations.generate(body.calculation_type, body.filters), "meta": meta(request)}

    @app.post("/calculation-code/execute", tags=["kpi"], dependencies=[Auth])
    async def execute_calculation(request: Request, body: CalculationExecuteRequest) -> dict[str, Any]:
        return {**calculations.execute(body.calculation_id, body.filters), "meta": meta(request)}

    @app.get("/analytics/kpi-definitions", tags=["kpi"], dependencies=[Auth])
    async def kpi_definitions(request: Request) -> dict[str, Any]:
        return {"kpis": KPI_DEFINITIONS, "total": len(KPI_DEFINITIONS), "meta": meta(request)}

    # -- admin: fault injection and request log (demo / tests) ----------------------------

    if settings.enable_admin:

        @app.post("/admin/faults", tags=["admin"], dependencies=[Auth])
        async def add_fault(rule: FaultRule) -> dict[str, Any]:
            faults.append({**rule.model_dump(), "remaining": rule.count})
            return {"faults": faults}

        @app.get("/admin/faults", tags=["admin"], dependencies=[Auth])
        async def list_faults() -> dict[str, Any]:
            return {"faults": faults}

        @app.delete("/admin/faults", tags=["admin"], dependencies=[Auth])
        async def clear_faults() -> dict[str, Any]:
            faults.clear()
            return {"faults": []}

        @app.get("/admin/requests", tags=["admin"], dependencies=[Auth])
        async def recent_requests(trace_id: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 100):
            rows = [r for r in request_log if trace_id is None or r["trace_id"] == trace_id]
            return {"requests": rows[-limit:]}

    return app


def build_app() -> FastAPI:
    settings = SimulatorSettings()
    configure_logging("alarm-api-simulator", settings.log_level)
    return create_app(settings)
