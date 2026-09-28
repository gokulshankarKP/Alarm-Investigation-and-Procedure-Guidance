"""Connector tests: payload/headers construction, retries, timeouts, error mapping, pagination."""

import httpx
import pytest

from connectors.alarm_api import (
    AlarmApiAuthError,
    AlarmApiClient,
    AlarmApiContractError,
    AlarmApiNotFoundError,
    AlarmApiTimeoutError,
    AlarmApiUnavailableError,
    AlarmApiValidationError,
    RequestContext,
)

CTX = RequestContext(trace_id="trace-unit-1", metadata_tag="mcp-tool:test")


def client_for(handler, retries=2) -> AlarmApiClient:
    return AlarmApiClient("http://api", "secret-token", max_retries=retries, backoff_base_s=0.0, transport=httpx.MockTransport(handler))


async def test_sends_auth_and_trace_headers_and_drops_none_params():
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = request.headers
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"results": [], "total": 0})

    await client_for(handler).search_assets(CTX, "pump", limit=3, site=None)
    assert seen["headers"]["authorization"] == "Bearer secret-token"
    assert seen["headers"]["trace_id"] == "trace-unit-1" and seen["headers"]["x-trace-id"] == "trace-unit-1"
    assert seen["headers"]["x-client-id"] == "alarm-mcp-server" and seen["headers"]["x-metadata-tag"] == "mcp-tool:test"
    assert seen["params"] == {"query": "pump", "limit": "3"}


async def test_retries_transient_errors_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": {"message": "busy"}}) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    result = await client_for(handler).kpi_definitions(CTX)
    assert result.attempts == 3 and len(result.retries) == 2
    assert result.meta()["api_status"] == 200


async def test_gives_up_after_max_retries_with_unavailable_error():
    def handler(request):
        return httpx.Response(503, json={"error": {"code": "X", "message": "down"}})

    with pytest.raises(AlarmApiUnavailableError) as exc:
        await client_for(handler, retries=1).kpi_definitions(CTX)
    assert exc.value.attempts == 2 and exc.value.retryable and exc.value.message == "down"
    assert exc.value.trace_id == "trace-unit-1"


async def test_timeout_is_mapped_and_retried():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(AlarmApiTimeoutError):
        await client_for(handler, retries=2).kpi_definitions(CTX)
    assert len(calls) == 3


@pytest.mark.parametrize(("status", "error"), [(401, AlarmApiAuthError), (404, AlarmApiNotFoundError), (422, AlarmApiValidationError)])
async def test_client_errors_are_not_retried(status, error):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "nope", "details": {"x": 1}}})

    with pytest.raises(error) as exc:
        await client_for(handler).kpi_definitions(CTX)
    assert len(calls) == 1 and exc.value.details == {"x": 1}


async def test_rate_limit_honours_retry_after():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"}) if len(calls) == 1 else httpx.Response(200, json={})

    assert (await client_for(handler).kpi_definitions(CTX)).attempts == 2


async def test_non_json_success_is_a_contract_error():
    with pytest.raises(AlarmApiContractError):
        await client_for(lambda r: httpx.Response(200, text="<html>")).kpi_definitions(CTX)


async def test_pagination_helper_follows_has_next():
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"data": [{"alarm_id": f"A{page}"}], "pagination": {"page": page, "has_next": page < 3}})

    rows, pagination, calls = await client_for(handler).list_all_alarms(CTX, max_pages=5, site="X")
    assert [r["alarm_id"] for r in rows] == ["A1", "A2", "A3"] and len(calls) == 3 and not pagination["has_next"]


async def test_path_segments_are_encoded():
    seen = {}

    def handler(request):
        seen["path"] = request.url.raw_path.decode()
        return httpx.Response(200, json={})

    await client_for(handler).asset_metadata(CTX, "../admin")
    assert seen["path"] == "/assets/..%2Fadmin/metadata"
