"""MCP client integration: real streamable-HTTP MCP server + simulator running in background threads."""

import pytest
from conftest import MCP_TOKEN

from copilot.config import CopilotSettings
from copilot.mcp_gateway import McpGateway, McpUnavailableError

pytestmark = pytest.mark.integration


def gateway(url: str, token: str = MCP_TOKEN) -> McpGateway:
    return McpGateway(CopilotSettings(MCP_SERVER_URL=url, MCP_AUTH_TOKEN=token, MCP_TOOL_TIMEOUT_S=15))


async def test_connect_discovers_tools_with_schemas(stack):
    async with gateway(stack.mcp_url).connect("trace-int-1", "conv-int") as session:
        assert len(session.catalog) == 13 and session.has("correlate_alarms")
        info = next(t for t in session.catalog if t.name == "get_alarms")
        assert info.read_only and info.output_schema and "page_size" in info.input_schema["properties"]
        assert session.records[0].tool == "tools/list" and session.records[0].status == "success"


async def test_invocation_propagates_trace_to_api(stack):
    async with gateway(stack.mcp_url).connect("trace-int-2", "conv-int-2") as session:
        rec = await session.call("search_assets", {"query": "Boiler Feed Pump 102"}, purpose="resolve")
    assert rec.status == "success" and rec.result["results"][0]["asset_id"] == "BFP-102"
    assert rec.api_calls[0]["trace_id"] == "trace-int-2"
    logged = stack.requests_for("trace-int-2")
    assert logged and logged[0]["metadata_tag"] == "mcp-tool:search_assets;conversation:conv-int-2"


async def test_output_of_one_tool_feeds_the_next(stack):
    async with gateway(stack.mcp_url).connect("trace-int-3") as session:
        found = await session.call("search_assets", {"query": "compressor", "site": "EastRefinery"}, purpose="find")
        ids = [r["asset_id"] for r in found.result["results"][:2]]
        corr = await session.call(
            "correlate_alarms",
            {"asset_ids": ids, "start_time": "2026-07-02T00:00:00Z", "end_time": "2026-09-30T00:00:00Z"},
            purpose="correlate",
        )
    assert ids == ["K-201", "K-202"] and corr.status == "success"
    assert "PCV-210" in {c["asset_id"] for c in corr.result["common_cause_candidates"]}


async def test_invalid_input_is_caught_client_side(stack):
    async with gateway(stack.mcp_url).connect("trace-int-4") as session:
        rec = await session.call("get_alarms", {"site": "NorthPlant", "page_size": "lots"}, purpose="bad")
        rec2 = await session.call("search_assets", {"query": "pump", "unexpected": 1}, purpose="bad")
    assert rec.status == "invalid_input" and rec.error["stage"] == "client_schema_validation"
    assert rec2.status in ("invalid_input", "success")  # additional properties allowed by schema -> server decides


async def test_server_side_semantic_error(stack):
    async with gateway(stack.mcp_url).connect("trace-int-5") as session:
        rec = await session.call("get_alarms", {}, purpose="no scope")
        missing = await session.call("get_asset_metadata", {"asset_id": "ZZ-999"}, purpose="missing")
    assert rec.status == "invalid_input" and rec.error["code"] == "INVALID_ARGUMENT"
    assert missing.status == "error" and missing.error["code"] == "NOT_FOUND"


async def test_unavailable_tool_is_reported_not_raised(stack):
    async with gateway(stack.mcp_url).connect("trace-int-6") as session:
        rec = await session.call("delete_all_alarms", {}, purpose="does not exist")
    assert rec.status == "unavailable" and rec.error["code"] == "TOOL_UNAVAILABLE"


async def test_partial_failure_with_retries_is_visible(stack):
    stack.inject_fault("/alarms/trends", status_code=503, count=10)
    async with gateway(stack.mcp_url).connect("trace-int-7") as session:
        bad = await session.call(
            "get_alarm_trends",
            {"site": "NorthPlant", "start_time": "2026-07-02T00:00:00Z", "end_time": "2026-09-30T00:00:00Z"},
            purpose="trend",
        )
        good = await session.call("search_assets", {"query": "deaerator"}, purpose="still works")
    assert bad.status == "error" and bad.error["code"] == "UPSTREAM_UNAVAILABLE" and bad.error["attempts"] == 3
    assert good.status == "success"


async def test_upstream_timeout_is_mapped(stack):
    stack.inject_fault("/analytics/kpi-definitions", mode="timeout", delay_seconds=5, count=3)
    async with gateway(stack.mcp_url).connect("trace-int-8") as session:
        rec = await session.call("list_kpi_definitions", {}, purpose="slow")
    assert rec.status == "error" and rec.error["code"] == "UPSTREAM_TIMEOUT"


async def test_wrong_token_and_unreachable_server_raise_unavailable(stack):
    with pytest.raises(McpUnavailableError):
        async with gateway(stack.mcp_url, token="wrong").connect("t"):
            pass
    with pytest.raises(McpUnavailableError):
        async with gateway("http://127.0.0.1:1/mcp").connect("t"):
            pass
