"""GUI tests with Streamlit's AppTest: the app renders chat, panels, citations and the MCP trace
for a real backend response, plus loading/error/empty states."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.e2e

APP = str(Path(__file__).resolve().parents[2] / "apps" / "frontend" / "copilot_ui" / "app.py")


@pytest.fixture
def real_response(stack, make_service):
    import asyncio

    resp = asyncio.run(make_service().chat("Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions."))
    return resp.model_dump(mode="json")


def _patch_backend(monkeypatch, *, chat=None, fail=False):
    from copilot_ui import api_client

    def _fail(*a, **k):
        raise api_client.BackendError("Cannot reach the copilot backend")

    monkeypatch.setattr(
        api_client,
        "health",
        _fail
        if fail
        else lambda: {"status": "ok", "components": {"mcp_server": {"status": "ok", "tools": 13}, "llm": {"status": "disabled"}}},
    )
    monkeypatch.setattr(
        api_client,
        "list_tools",
        _fail
        if fail
        else lambda: [
            {"name": "search_assets", "description": "Resolve assets", "input_schema": {"type": "object"}, "output_schema": None}
        ],
    )
    monkeypatch.setattr(api_client, "chat", _fail if fail else chat)


def test_empty_state_and_tool_discovery(monkeypatch):
    _patch_backend(monkeypatch, chat=lambda m, c: {})
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("Ask about an asset" in i.value for i in at.info)
    assert any("search_assets" in e.label for e in at.sidebar.expander)


def test_renders_full_answer_with_panels_citations_and_trace(monkeypatch, real_response):
    _patch_backend(monkeypatch, chat=lambda m, c: real_response)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("Show active critical alarms for Boiler Feed Pump 102").run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels[0].endswith("Alarm summary") and "Citations" in labels[2] and "MCP trace" in labels[3]
    assert any(m.value.startswith("### Summary") for m in at.markdown)
    assert any("SOP-BFP-001" in e.label for e in at.expander)  # citation expanders
    assert any("search_assets" in e.label and "T2" in e.label for e in at.expander)  # trace expanders
    assert len(at.dataframe) >= 3


def test_backend_errors_are_shown(monkeypatch):
    _patch_backend(monkeypatch, fail=True)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("Cannot reach" in e.value for e in at.sidebar.error)
    at.chat_input[0].set_value("hello").run()
    assert any("Cannot reach" in e.value for e in at.error)
