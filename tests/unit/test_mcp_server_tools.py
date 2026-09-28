"""MCP server tool tests (in-process, API calls routed to the simulator via ASGI transport)."""

import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from alarm_mcp.config import McpServerSettings
from alarm_mcp.server import create_server

EXPECTED_TOOLS = {
    "search_assets",
    "get_asset_metadata",
    "get_alarms",
    "get_alarm_details",
    "summarize_alarms",
    "get_alarm_trends",
    "correlate_alarms",
    "analyze_alarm_floods",
    "find_rationalization_candidates",
    "score_alarm_priority",
    "get_operator_recommendations",
    "calculate_alarm_kpi",
    "list_kpi_definitions",
}
WINDOW = {"start_time": "2026-07-02T00:00:00Z", "end_time": "2026-09-30T00:00:00Z"}


@pytest.fixture
def mcp(sim_app):
    settings = McpServerSettings(ALARM_API_MAX_RETRIES=1, ALARM_API_BACKOFF_S=0.0)
    return create_server(settings, api_transport=httpx.ASGITransport(app=sim_app))


async def call(mcp, name, args):
    _content, structured = await mcp.call_tool(name, args)
    return structured


def error_of(exc: ToolError) -> dict:
    text = str(exc)
    return json.loads(text[text.index("{") :])["error"]


async def test_all_tools_registered_with_schemas_and_read_only_annotations(mcp):
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    for tool in tools.values():
        assert tool.description and len(tool.description) > 30
        assert tool.inputSchema["type"] == "object"
        assert tool.outputSchema is not None and "meta" in tool.outputSchema["properties"]
        assert tool.annotations.readOnlyHint is True
    assert "query" in tools["search_assets"].inputSchema["required"]
    assert tools["get_alarms"].inputSchema["properties"]["page_size"]["maximum"] == 200


async def test_search_assets_returns_typed_result_with_trace_meta(mcp, sim_app):
    out = await call(mcp, "search_assets", {"query": "Boiler Feed Pump 101", "limit": 3})
    assert out["results"][0]["asset_id"] == "BFP-101"
    meta = out["meta"]
    assert meta["tool"] == "search_assets" and meta["trace_id"].startswith("mcp-")
    assert meta["api_calls"][0]["api_status"] == 200 and meta["api_calls"][0]["api_endpoint"] == "GET /assets/search"
    logged = [e for e in sim_app.state.request_log if e["trace_id"] == meta["trace_id"]]
    assert logged and logged[0]["client_id"] == "alarm-mcp-server" and logged[0]["metadata_tag"] == "mcp-tool:search_assets"


async def test_schema_validation_rejects_bad_arguments(mcp):
    with pytest.raises(ToolError, match="page_size"):
        await mcp.call_tool("get_alarms", {"site": "EastRefinery", "page_size": 1000})
    with pytest.raises(ToolError, match="query"):
        await mcp.call_tool("search_assets", {"query": "x"})  # min_length 2
    with pytest.raises(ToolError):
        await mcp.call_tool("score_alarm_priority", {"alarm_id": "../../etc/passwd"})  # pattern


async def test_semantic_validation_errors_are_invalid_argument(mcp):
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("get_alarms", {})
    assert error_of(exc.value)["code"] == "INVALID_ARGUMENT"
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("summarize_alarms", {"start_time": "2026-09-01T00:00:00Z", "end_time": "2026-08-01T00:00:00Z"})
    assert "start_time must be before end_time" in error_of(exc.value)["message"]


async def test_not_found_is_mapped_to_tool_error(mcp):
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("get_asset_metadata", {"asset_id": "NOPE-1"})
    err = error_of(exc.value)
    assert err["code"] == "NOT_FOUND" and err["status_code"] == 404 and err["retryable"] is False
    assert err["tool"] == "get_asset_metadata" and err["trace_id"]


async def test_upstream_outage_is_retried_then_mapped(mcp, sim_client):
    from conftest import AUTH

    sim_client.post("/admin/faults", headers=AUTH, json={"path_prefix": "/alarms/correlation", "status_code": 503, "count": 5})
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("correlate_alarms", {"asset_ids": ["BFP-101"], **WINDOW})
    err = error_of(exc.value)
    assert err["code"] == "UPSTREAM_UNAVAILABLE" and err["attempts"] == 2 and err["retryable"] is True


async def test_transient_failure_recovers_and_reports_retry(mcp, sim_client):
    from conftest import AUTH

    sim_client.post("/admin/faults", headers=AUTH, json={"path_prefix": "/alarms/priority-score", "status_code": 502, "count": 1})
    active = await call(mcp, "get_alarms", {"site": "EastRefinery", "status": "active"})
    out = await call(mcp, "score_alarm_priority", {"alarm_id": active["alarms"][0]["alarm_id"]})
    assert out["meta"]["api_calls"][0]["attempts"] == 2
    assert out["meta"]["api_calls"][0]["retries"] == ["UPSTREAM_UNAVAILABLE (HTTP 502)"]


async def test_pagination_fetch_all_pages(mcp):
    out = await call(mcp, "get_alarms", {"site": "EastRefinery", "page_size": 20, "fetch_all_pages": True, **WINDOW})
    assert out["pages_fetched"] > 1 and len(out["meta"]["api_calls"]) == out["pages_fetched"]
    single = await call(mcp, "get_alarms", {"site": "EastRefinery", "page_size": 20, **WINDOW})
    assert single["pages_fetched"] == 1 and single["truncated"] is True


async def test_output_contract_violation_is_detected():
    def bad_api(request):
        return httpx.Response(200, json={"results": [{"asset_id": "X"}], "total": 1})  # missing required fields

    mcp = create_server(McpServerSettings(), api_transport=httpx.MockTransport(bad_api))
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("search_assets", {"query": "pump"})
    assert error_of(exc.value)["code"] == "UPSTREAM_CONTRACT_ERROR"


async def test_kpi_tool_chains_generate_and_execute(mcp, sim_app):
    out = await call(
        mcp,
        "calculate_alarm_kpi",
        {
            "calculation_type": "alarm_flood_index",
            "unit": "Unit 2",
            "start_time": "2026-05-01T00:00:00Z",
            "end_time": "2026-07-01T00:00:00Z",
        },
    )
    endpoints = [c["api_endpoint"] for c in out["meta"]["api_calls"]]
    assert endpoints == ["POST /calculation-code/generate", "POST /calculation-code/execute"]
    assert out["result"]["breakdown"]["flood_count"] >= 1 and out["code"]


async def test_recommendation_and_correlation_tools(mcp):
    active = await call(mcp, "get_alarms", {"asset_ids": ["BFP-102"], "status": "active"})
    critical = next(a for a in active["alarms"] if a["severity"] == "critical")
    rec = await call(mcp, "get_operator_recommendations", {"alarm_id": critical["alarm_id"]})
    assert rec["recommendations"] and rec["alarm_code"] == "BFP-SUCT-P-LL"
    corr = await call(mcp, "correlate_alarms", {"asset_ids": ["M-501", "M-502"], **WINDOW, "severity_threshold": "high", "min_support": 1})
    assert any(c["asset_id"] == "TR-501" for c in corr["common_cause_candidates"]) or corr["pairs"]
