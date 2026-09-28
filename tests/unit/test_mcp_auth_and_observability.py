import json
import logging

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from alarm_mcp.auth import BearerAuthMiddleware
from shared.observability import JsonFormatter, redact, trace_id_var


def _app():
    async def ok(request):
        return PlainTextResponse("ok")

    return BearerAuthMiddleware(Starlette(routes=[Route("/mcp", ok, methods=["POST"]), Route("/health", ok)]), "s3cret")


def test_mcp_endpoint_requires_bearer_token():
    client = TestClient(_app())
    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays public


def test_redaction_masks_credentials_but_not_counters():
    data = redact(
        {
            "Authorization": "Bearer abc.def",
            "db_password": "p",
            "auth_token": "t",
            "input_tokens": 12,
            "nested": [{"api_key": "k", "note": "sent Bearer xyz123 to api"}],
        }
    )
    assert data["Authorization"] == data["db_password"] == data["auth_token"] == "***"
    assert data["input_tokens"] == 12
    assert data["nested"][0]["api_key"] == "***" and "xyz123" not in data["nested"][0]["note"]


def test_json_logs_carry_trace_id_and_are_redacted():
    token = trace_id_var.set("trace-log-1")
    try:
        record = logging.makeLogRecord(
            {"msg": "call", "levelno": 20, "levelname": "INFO", "name": "t", "headers": {"Authorization": "Bearer secret"}}
        )
        line = json.loads(JsonFormatter("svc").format(record))
    finally:
        trace_id_var.reset(token)
    assert line["trace_id"] == "trace-log-1" and line["service"] == "svc"
    assert line["headers"]["Authorization"] == "***"
