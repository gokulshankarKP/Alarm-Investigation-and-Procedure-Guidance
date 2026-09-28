"""Async HTTP client for the Alarm Management API.

Responsibilities (kept out of the MCP layer so they are reusable and unit-testable):

* bearer authentication (token never logged)
* trace propagation: ``trace_id`` (+ ``x-trace-id``), ``x-client-id``, ``x-metadata-tag``
* per-request timeout, retry with exponential backoff + jitter on 429 / 5xx / timeouts /
  connection errors, honouring ``Retry-After``
* mapping of HTTP errors and the API error envelope to typed ``AlarmApiError`` subclasses
* pagination helper for ``GET /alarms``
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from connectors.alarm_api.errors import (
    AlarmApiContractError,
    AlarmApiError,
    AlarmApiTimeoutError,
    AlarmApiUnavailableError,
    error_for_status,
)
from shared.observability import log_event

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 502, 503, 504}


@dataclass(frozen=True)
class RequestContext:
    """Per-call trace metadata forwarded to the API."""

    trace_id: str
    client_id: str = "alarm-mcp-server"
    metadata_tag: str | None = None


@dataclass
class ApiResult:
    data: dict[str, Any]
    status_code: int
    attempts: int
    duration_ms: float
    endpoint: str
    trace_id: str
    request_id: str | None = None
    retries: list[str] = field(default_factory=list)  # reason for each retry

    def meta(self) -> dict[str, Any]:
        return {
            "api_endpoint": self.endpoint,
            "api_status": self.status_code,
            "attempts": self.attempts,
            "retries": self.retries,
            "duration_ms": self.duration_ms,
            "trace_id": self.trace_id,
            "api_request_id": self.request_id,
        }


class AlarmApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 10.0,
        max_retries: int = 2,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 4.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._max_retries = max_retries
        self._backoff_base = backoff_base_s
        self._backoff_max = backoff_max_s
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AlarmApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- core -----------------------------------------------------------------------------

    def _headers(self, ctx: RequestContext) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "trace_id": ctx.trace_id,
            "x-trace-id": ctx.trace_id,
            "x-client-id": ctx.client_id,
        }
        if ctx.metadata_tag:
            headers["x-metadata-tag"] = ctx.metadata_tag
        return headers

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self._backoff_max)
            except ValueError:
                pass
        base = min(self._backoff_base * 2 ** (attempt - 1), self._backoff_max)
        return base * random.uniform(0.8, 1.2)

    async def request(
        self,
        method: str,
        path: str,
        ctx: RequestContext,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> ApiResult:
        endpoint = f"{method} {path}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        attempts = self._max_retries + 1
        retries: list[str] = []
        started = time.perf_counter()

        for attempt in range(1, attempts + 1):
            error: AlarmApiError
            retry_after = None
            try:
                response = await self._client.request(method, path, params=clean_params, json=json, headers=self._headers(ctx))
            except httpx.TimeoutException as exc:
                error = AlarmApiTimeoutError(f"Alarm API timed out ({type(exc).__name__})")
            except httpx.TransportError as exc:
                error = AlarmApiUnavailableError(f"Alarm API unreachable ({type(exc).__name__})")
            else:
                if response.is_success:
                    try:
                        data = response.json()
                    except ValueError:
                        raise AlarmApiContractError(
                            "Alarm API returned a non-JSON body",
                            status_code=response.status_code,
                            attempts=attempt,
                            trace_id=ctx.trace_id,
                            endpoint=endpoint,
                        ) from None
                    if not isinstance(data, dict):
                        raise AlarmApiContractError(
                            "Alarm API returned a non-object JSON body",
                            status_code=response.status_code,
                            attempts=attempt,
                            trace_id=ctx.trace_id,
                            endpoint=endpoint,
                        )
                    result = ApiResult(
                        data=data,
                        status_code=response.status_code,
                        attempts=attempt,
                        duration_ms=round((time.perf_counter() - started) * 1000, 1),
                        endpoint=endpoint,
                        trace_id=ctx.trace_id,
                        request_id=response.headers.get("x-request-id"),
                        retries=retries,
                    )
                    log_event(
                        logger,
                        "alarm_api_call",
                        endpoint=endpoint,
                        status=response.status_code,
                        attempts=attempt,
                        duration_ms=result.duration_ms,
                    )
                    return result
                error = self._map_error(response)
                retry_after = response.headers.get("Retry-After")
                if response.status_code not in _RETRYABLE_STATUS:
                    error.attempts, error.trace_id, error.endpoint = attempt, ctx.trace_id, endpoint
                    log_event(
                        logger,
                        "alarm_api_error",
                        logging.WARNING,
                        endpoint=endpoint,
                        status=response.status_code,
                        code=error.code,
                        attempts=attempt,
                    )
                    raise error

            if attempt == attempts:
                error.attempts, error.trace_id, error.endpoint = attempt, ctx.trace_id, endpoint
                log_event(
                    logger,
                    "alarm_api_error",
                    logging.WARNING,
                    endpoint=endpoint,
                    status=error.status_code,
                    code=error.code,
                    attempts=attempt,
                )
                raise error
            reason = f"{error.code}" + (f" (HTTP {error.status_code})" if error.status_code else "")
            retries.append(reason)
            delay = self._delay(attempt, retry_after)
            log_event(
                logger, "alarm_api_retry", logging.WARNING, endpoint=endpoint, attempt=attempt, reason=reason, delay_s=round(delay, 2)
            )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _map_error(response: httpx.Response) -> AlarmApiError:
        message, details = f"HTTP {response.status_code}", None
        try:
            body = response.json()
            envelope = body.get("error") if isinstance(body, dict) else None
            if isinstance(envelope, dict):
                message = envelope.get("message") or message
                details = envelope.get("details")
        except ValueError:
            pass
        return error_for_status(response.status_code)(message, status_code=response.status_code, details=details)

    # -- endpoints (Postman contract) -------------------------------------------------------

    async def health(self, ctx: RequestContext) -> ApiResult:
        return await self.request("GET", "/health", ctx)

    async def search_assets(
        self,
        ctx: RequestContext,
        query: str,
        *,
        limit: int = 10,
        site: str | None = None,
        unit: str | None = None,
        asset_class: str | None = None,
    ) -> ApiResult:
        return await self.request(
            "GET", "/assets/search", ctx, params={"query": query, "limit": limit, "site": site, "unit": unit, "asset_class": asset_class}
        )

    async def asset_metadata(self, ctx: RequestContext, asset_id: str) -> ApiResult:
        return await self.request("GET", f"/assets/{_segment(asset_id)}/metadata", ctx)

    async def list_alarms(self, ctx: RequestContext, **params: Any) -> ApiResult:
        return await self.request("GET", "/alarms", ctx, params=params)

    async def list_all_alarms(self, ctx: RequestContext, *, max_pages: int = 5, **params: Any) -> tuple[list[dict], dict, list[ApiResult]]:
        """Follow pagination until ``has_next`` is false or ``max_pages`` pages were read."""
        page = int(params.pop("page", 1))
        rows: list[dict] = []
        calls: list[ApiResult] = []
        pagination: dict = {}
        for _ in range(max_pages):
            result = await self.list_alarms(ctx, page=page, **params)
            calls.append(result)
            data = result.data.get("data")
            pagination = result.data.get("pagination") or {}
            if not isinstance(data, list):
                raise AlarmApiContractError("GET /alarms response has no 'data' list", endpoint="GET /alarms", trace_id=ctx.trace_id)
            rows.extend(data)
            if not pagination.get("has_next"):
                break
            page += 1
        return rows, pagination, calls

    async def get_alarm(self, ctx: RequestContext, alarm_id: str) -> ApiResult:
        return await self.request("GET", f"/alarms/{_segment(alarm_id)}", ctx)

    async def alarm_summary(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/summary", ctx, json=body)

    async def alarm_trends(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/trends", ctx, json=body)

    async def alarm_correlation(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/correlation", ctx, json=body)

    async def flood_analysis(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/flood-analysis", ctx, json=body)

    async def rationalization_candidates(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/rationalization-candidates", ctx, json=body)

    async def priority_score(self, ctx: RequestContext, alarm_id: str) -> ApiResult:
        return await self.request("POST", "/alarms/priority-score", ctx, json={"alarm_id": alarm_id})

    async def operator_recommendations(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/recommendations/operator-actions", ctx, json=body)

    async def generate_calculation(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/calculation-code/generate", ctx, json=body)

    async def execute_calculation(self, ctx: RequestContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/calculation-code/execute", ctx, json=body)

    async def kpi_definitions(self, ctx: RequestContext) -> ApiResult:
        return await self.request("GET", "/analytics/kpi-definitions", ctx)


def _segment(value: str) -> str:
    """Encode a path segment so identifiers cannot alter the request path."""
    from urllib.parse import quote

    return quote(value, safe="")
