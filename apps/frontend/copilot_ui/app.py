"""Streamlit GUI: ``streamlit run apps/frontend/copilot_ui/app.py``."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `streamlit run` without install

from copilot_ui import api_client
from copilot_ui.components import (
    render_alarm_panel,
    render_causes_actions,
    render_citations,
    render_header,
    render_trace,
)

EXAMPLES = [
    "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely "
    "contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source evidence.",
    "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.",
    "Why are compressor discharge pressure alarms repeatedly occurring?",
    "Which alarm has the highest priority in EastRefinery, and why?",
    "What related assets should be inspected for the motor trip on M-501?",
    "Which operating procedure applies to this alarm?",
    "Are the API recommendations consistent with the maintenance manual?",
]

st.set_page_config(page_title="Alarm Investigation Copilot", page_icon="🚨", layout="wide")
state = st.session_state
state.setdefault("conversation_id", f"conv-{uuid.uuid4().hex[:12]}")
state.setdefault("messages", [])
state.setdefault("pending", None)


# -- sidebar --------------------------------------------------------------------------------
with st.sidebar:
    st.header("🚨 Alarm Copilot")
    st.caption(f"Backend: `{api_client.BACKEND_URL}`  \nConversation: `{state.conversation_id}`")
    if st.button("New conversation", width="stretch"):
        state.conversation_id = f"conv-{uuid.uuid4().hex[:12]}"
        state.messages = []
        st.rerun()

    st.subheader("System health")
    try:
        health = api_client.health()
        st.markdown(f"Overall: **{health['status']}**")
        for name, comp in health["components"].items():
            icon = {"ok": "🟢", "disabled": "⚪"}.get(comp["status"], "🔴")
            detail = ", ".join(f"{k}={v}" for k, v in comp.items() if k not in ("status", "error"))
            st.caption(f"{icon} **{name}** {detail}" + (f"  \n{comp['error'][:140]}" if comp.get("error") else ""))
    except api_client.BackendError as exc:
        st.error(str(exc))

    st.subheader("MCP tool discovery")
    try:
        tools = api_client.list_tools()
        st.caption(f"{len(tools)} tools discovered from the Alarm Management MCP server")
        for tool in tools:
            with st.expander(f"🔧 {tool['name']}"):
                st.write(tool["description"])
                st.markdown("**Input schema**")
                st.code(json.dumps(tool["input_schema"], indent=2), language="json")
                if tool.get("output_schema"):
                    st.markdown("**Output schema**")
                    st.code(json.dumps(tool["output_schema"], indent=2)[:6000], language="json")
    except api_client.BackendError as exc:
        st.warning(f"Tool discovery failed: {exc}")

    st.subheader("Examples")
    for i, example in enumerate(EXAMPLES):
        if st.button(example[:70] + ("…" if len(example) > 70 else ""), key=f"ex{i}", width="stretch"):
            state.pending = example


# -- main -----------------------------------------------------------------------------------
st.title("Alarm Investigation & Procedure Guidance Copilot")
st.caption(
    "Alarm data via the Alarm Management **MCP server** · procedures via **document RAG** · every claim cited "
    "([T#] = MCP tool step, [S#] = document source)"
)


def render_response(resp: dict) -> None:
    render_header(resp)
    st.markdown(resp["answer_markdown"])
    tabs = st.tabs(
        [
            "📊 Alarm summary",
            "🧭 Causes & actions",
            f"📚 Citations ({len(resp['citations'])})",
            f"🛠️ MCP trace ({len(resp['tool_trace'])})",
            "🧾 Raw response",
        ]
    )
    with tabs[0]:
        render_alarm_panel(resp)
    with tabs[1]:
        render_causes_actions(resp)
    with tabs[2]:
        render_citations(resp)
    with tabs[3]:
        render_trace(resp)
    with tabs[4]:
        st.code(json.dumps(resp, indent=2, default=str)[:60000], language="json")


if not state.messages and not state.pending:
    st.info(
        "Ask about an asset, alarm, site or procedure, or pick an example in the sidebar. "
        "With a CPU-only local LLM an answer can take a few minutes."
    )

for message in state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        elif "error" in message:
            st.error(message["error"])
        else:
            render_response(message["response"])

prompt = st.chat_input("e.g. Show active critical alarms for Boiler Feed Pump 102") or state.pending
if prompt:
    state.pending = None
    state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with (
        st.chat_message("assistant"),
        st.spinner("Investigating: discovering MCP tools → querying alarm data → retrieving procedures → composing answer…"),
    ):
        try:
            response = api_client.chat(prompt, state.conversation_id)
            state.messages.append({"role": "assistant", "response": response})
        except api_client.BackendError as exc:
            state.messages.append({"role": "assistant", "error": str(exc)})
    st.rerun()
