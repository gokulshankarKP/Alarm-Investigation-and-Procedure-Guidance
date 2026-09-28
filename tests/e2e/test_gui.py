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

    def _stream(message, conversation_id):
        if fail:
            _fail()
        response = chat(message, conversation_id)
        yield {"type": "stage", "stage": "understand", "label": "Understanding the question"}
        yield {"type": "discovery", "tools": 13, "duration_ms": 12}
        yield {"type": "intent", "intent": "active_alarm_triage", "method": "rules", "entities": {"asset_names": ["Boiler Feed Pump 102"]}}
        for t in response.get("tool_trace", []):
            if t["tool"] == "tools/list":
                continue
            yield {"type": "tool_start", "step": t["step"], "tool": t["tool"], "arguments": t["arguments"], "purpose": t["purpose"]}
            yield {
                "type": "tool_end",
                "step": t["step"],
                "tool": t["tool"],
                "status": t["status"],
                "duration_ms": t["duration_ms"],
                "retries": len(t["retries"]),
                "error_code": None,
            }
        yield {"type": "retrieval", "sources": len(response.get("citations", [])), "quarantined": 0, "low_confidence": False, "queries": 4}
        yield {"type": "result", "response": response}

    monkeypatch.setattr(api_client, "chat_stream", _stream)


def test_empty_state_and_tool_discovery(monkeypatch):
    _patch_backend(monkeypatch, chat=lambda m, c: {})
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("Ask about an asset" in i.value for i in at.info)
    assert any(e.label == "MCP tools (1)" for e in at.sidebar.expander)
    assert any("search_assets" in m.value for m in at.sidebar.markdown)


def test_renders_full_answer_with_panels_citations_and_trace(monkeypatch, real_response):
    _patch_backend(monkeypatch, chat=lambda m, c: real_response)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("Show active critical alarms for Boiler Feed Pump 102").run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels[:2] == ["Overview", "Causes & actions"] and labels[2].startswith("Sources") and labels[3].startswith("Trace")
    assert any('class="answer"' in m.value for m in at.markdown)  # concise summary first
    assert any('class="actions"' in m.value for m in at.markdown)  # top actions with citation pills
    assert not any("### Summary" in m.value or "### Recommended actions" in m.value for m in at.markdown)  # no long report in chat
    assert any("SOP-BFP-001" in e.label for e in at.expander)  # source expanders
    trace = at.selectbox(key="trace-1")
    assert any("search_assets" in o for o in trace.options)
    assert any(m.value == "Active alarms" or "Active alarms" in m.value for m in at.markdown)
    assert len(at.dataframe) >= 3
    # live tool activity is kept as a collapsed log with the answer (Claude-style tool use)
    log = next(s for s in at.status if s.label.startswith("Used "))  # expanders with an icon render as status
    assert "tools" in log.label and any("search_assets(" in m.value for m in log.markdown)
    # a second answer collapses the details of the first behind a toggle
    at.chat_input[0].set_value("again").run()
    assert not at.exception and len(at.toggle) == 1


def test_backend_errors_are_shown(monkeypatch):
    _patch_backend(monkeypatch, fail=True)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("Cannot reach" in e.value for e in at.sidebar.error)
    at.chat_input[0].set_value("hello").run()
    assert any("Cannot reach" in e.value for e in at.error)
