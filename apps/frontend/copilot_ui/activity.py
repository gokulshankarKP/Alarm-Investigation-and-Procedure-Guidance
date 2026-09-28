"""Live activity feed: shows workflow stages and MCP tool calls while the answer is produced
(similar to how Claude shows its tool use), then keeps a collapsed log with each answer."""

from __future__ import annotations

import html
import json
from typing import Any

import streamlit as st

STATUS_MARK = {"success": "✓", "error": "✗", "timeout": "✗", "invalid_input": "✗", "unavailable": "✗", "skipped": "–"}


def format_call(tool: str, arguments: dict[str, Any], limit: int = 90) -> str:
    """``search_assets(query="Boiler Feed Pump 101", limit=5)`` - compact, truncated argument list."""
    parts = []
    for key, value in arguments.items():
        if isinstance(value, list):
            text = "[" + ", ".join(str(v) for v in value[:3]) + (", …" if len(value) > 3 else "") + "]"
        elif isinstance(value, str):
            text = json.dumps(value[:40] + ("…" if len(value) > 40 else ""))
        else:
            text = json.dumps(value)
        parts.append(f"{key}={text}")
    args = ", ".join(parts)
    if len(args) > limit:
        args = args[: limit - 1] + "…"
    return f"{tool}({args})"


def _line(body: str, kind: str = "") -> str:
    return f'<div class="act {kind}">{body}</div>'


def stage_line(label: str) -> str:
    return _line(html.escape(label), "stage")


def tool_line(call: str, *, mark: str = "", detail: str = "", failed: bool = False) -> str:
    icon = f'<span class="mark {"bad" if failed else "ok"}">{mark}</span>' if mark else '<span class="spin small"></span>'
    extra = f' <span class="muted">· {html.escape(detail)}</span>' if detail else ""
    return _line(f"{icon}<code>{html.escape(call)}</code>{extra}", "tool")


class LiveActivity:
    """Consumes backend progress events and renders them in an always-visible bordered container:
    a title line with the current step, then one line per stage / tool call (updated in place)."""

    def __init__(self, box: Any) -> None:
        self.box = box
        self._title = box.empty()
        self._set_title("Working…")
        self.lines: list[str] = []  # final HTML lines, kept with the message for the history view
        self._slots: dict[int, tuple[Any, int, str]] = {}  # step -> (placeholder, line index, call text)
        self._tools = 0

    def _set_title(self, text: str, done: bool = False) -> None:
        icon = '<span class="mark ok">✓</span>' if done else '<span class="spin"></span>'
        self._title.markdown(f'<div class="activity-title">{icon} {html.escape(text)}</div>', unsafe_allow_html=True)

    def _add(self, text: str) -> int:
        self.lines.append(text)
        self.box.markdown(text, unsafe_allow_html=True)
        return len(self.lines) - 1

    def handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "stage":
            self._set_title(f"{event['label']}…")
            self._add(stage_line(event["label"]))
        elif kind == "discovery":
            self._add(_line(f"Connected to MCP server · {event['tools']} tools available", "stage"))
        elif kind == "intent":
            entities = event.get("entities") or {}
            scope = ", ".join(entities.get("asset_ids", []) + entities.get("asset_names", []) + entities.get("sites", []))
            text = f"Intent: <b>{html.escape(event['intent'].replace('_', ' '))}</b>" + (f" · {html.escape(scope)}" if scope else "")
            self._add(_line(text))
        elif kind == "tool_start":
            call = format_call(event["tool"], event.get("arguments") or {})
            text = tool_line(call)
            placeholder = self.box.empty()
            placeholder.markdown(text, unsafe_allow_html=True)
            self.lines.append(text)
            self._slots[event["step"]] = (placeholder, len(self.lines) - 1, call)
            self._set_title(f"Calling {event['tool']}…")
        elif kind == "tool_end":
            self._tools += 1
            slot = self._slots.pop(event["step"], None)
            call = slot[2] if slot else event["tool"]
            failed = event["status"] != "success"
            detail = f"{event['duration_ms']:.0f} ms"
            if event.get("retries"):
                detail += f" · retried {event['retries']}×"
            if failed:
                detail += f" · {event.get('error_code') or event['status']}"
            text = tool_line(call, mark=STATUS_MARK.get(event["status"], "•"), detail=detail, failed=failed)
            if slot:
                slot[0].markdown(text, unsafe_allow_html=True)
                self.lines[slot[1]] = text
            else:
                self._add(text)
        elif kind == "retrieval":
            note = f" · {event['quarantined']} quarantined" if event.get("quarantined") else ""
            conf = " · low confidence" if event.get("low_confidence") else ""
            self._add(_line(f"Retrieved {event['sources']} document sources from {event['queries']} searches{note}{conf}"))
        elif kind == "mcp_unavailable":
            self._add(_line("⚠️ MCP server unreachable: continuing with documents only", "warn"))

    def finish(self, response: dict[str, Any]) -> None:
        seconds = response.get("timings_ms", {}).get("total", 0) / 1000
        self._set_title(summary_label(self._tools, len(response.get("citations", [])), seconds), done=True)

    def fail(self, message: str) -> None:
        self._set_title("Failed", done=True)
        self.box.markdown(_line(f"✗ {html.escape(message)}", "warn"), unsafe_allow_html=True)


def summary_label(tools: int, sources: int, seconds: float) -> str:
    return f"Used {tools} tool{'s' if tools != 1 else ''} · {sources} sources · {seconds:.1f}s"


def render_activity_log(lines: list[str], response: dict[str, Any]) -> None:
    """Collapsed activity log shown above each answer in the conversation history."""
    if not lines:
        return
    tools = sum(1 for t in response.get("tool_trace", []) if t["tool"] != "tools/list")
    seconds = response.get("timings_ms", {}).get("total", 0) / 1000
    with st.expander(summary_label(tools, len(response.get("citations", [])), seconds), icon="🛠️"):
        st.markdown("".join(lines), unsafe_allow_html=True)
