"""Streamlit GUI: ``streamlit run apps/frontend/copilot_ui/app.py``."""

from __future__ import annotations

import html
import sys
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `streamlit run` without install

from copilot_ui import api_client
from copilot_ui.activity import LiveActivity, render_activity_log
from copilot_ui.components import inject_css, render_answer, render_details

EXAMPLES = [
    (
        "Recurring BFP-101 alarms",
        "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely contributing "
        "factors, retrieve the relevant operating procedure, and provide recommended actions with source evidence.",
    ),
    ("Critical alarms on BFP-102", "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions."),
    ("Compressor pressure alarms", "Why are compressor discharge pressure alarms repeatedly occurring?"),
    ("Top priority in EastRefinery", "Which alarm has the highest priority in EastRefinery, and why?"),
    ("Motor trip on M-501", "What related assets should be inspected for the motor trip on M-501?"),
    ("Check API recommendations", "Are the API recommendations consistent with the maintenance manual?"),
]

st.set_page_config(page_title="Alarm Investigation Copilot", page_icon="🛡️", layout="wide")
inject_css()
state = st.session_state
state.setdefault("conversation_id", f"conv-{uuid.uuid4().hex[:12]}")
state.setdefault("messages", [])
state.setdefault("pending", None)


# -- sidebar --------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛡️ Alarm Copilot")
    st.caption("Alarm investigation & procedure guidance")
    if st.button("New conversation", icon="➕", width="stretch"):
        state.conversation_id = f"conv-{uuid.uuid4().hex[:12]}"
        state.messages = []
        st.rerun()

    st.markdown("**Try asking**")
    for i, (label, question) in enumerate(EXAMPLES):
        if st.button(label, key=f"ex{i}", width="stretch", help=question):
            state.pending = question

    st.divider()
    st.markdown("**System status**")
    try:
        health = api_client.health()
        names = {"mcp_server": "MCP server", "rag_index": "Knowledge base", "llm": "LLM"}
        for name, comp in health["components"].items():
            dot = {"ok": "ok", "disabled": "off"}.get(comp["status"], "bad")
            if comp["status"] == "unavailable":
                detail = "unavailable"
            elif "tools" in comp:
                detail = f"{comp['tools']} tools"
            elif "chunks" in comp:
                detail = f"{comp['chunks']} passages"
            else:
                detail = comp.get("model", comp["status"])
            st.markdown(
                f'<div class="status-row"><span class="dot {dot}"></span>{names.get(name, name)} '
                f"<small>· {html.escape(str(detail))}</small></div>",
                unsafe_allow_html=True,
            )
    except api_client.BackendError as exc:
        st.error(str(exc))

    try:
        tools = api_client.list_tools()
        with st.expander(f"MCP tools ({len(tools)})"):
            for tool in tools:
                st.markdown(f"**`{tool['name']}`**  \n<small>{html.escape(tool['description'][:160])}</small>", unsafe_allow_html=True)
                st.json({"input": tool["input_schema"], "output": tool.get("output_schema")}, expanded=False)
    except api_client.BackendError:
        pass
    st.caption(f"Conversation `{state.conversation_id}`")


# -- main -----------------------------------------------------------------------------------
st.markdown(
    '<p class="app-title">Alarm Investigation Copilot</p>'
    '<p class="app-subtitle">Live alarm data through MCP tools, procedures from plant documents, '
    "every statement cited: <b>[T#]</b> tool step, <b>[S#]</b> document source.</p>",
    unsafe_allow_html=True,
)

typed = st.chat_input("Ask about an alarm, asset or procedure…")

if not state.messages and not state.pending and not typed:
    st.info("Ask about an asset, alarm, site or procedure, or start with one of these:")
    cols = st.columns(3)
    for i, (label, question) in enumerate(EXAMPLES[:3]):
        if cols[i].button(label, key=f"start{i}", width="stretch", help=question):
            state.pending = question
            st.rerun()

last_assistant = max((i for i, m in enumerate(state.messages) if m["role"] == "assistant"), default=-1)
for index, message in enumerate(state.messages):
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        elif "error" in message:
            st.error(message["error"])
        else:
            render_activity_log(message.get("activity", []), message["response"])
            render_answer(message["response"])
            if index == last_assistant or st.toggle("Show details", key=f"details-{index}"):
                render_details(message["response"], key=str(index))

prompt = typed or state.pending
if prompt:
    state.pending = None
    state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        feed = LiveActivity(st.container(border=True))
        try:
            response = None
            for event in api_client.chat_stream(prompt, state.conversation_id):
                if event["type"] == "result":
                    response = event["response"]
                elif event["type"] == "error":
                    raise api_client.BackendError(event["message"])
                else:
                    feed.handle(event)
            if response is None:
                raise api_client.BackendError("The backend closed the stream without an answer")
            feed.finish(response)
            state.messages.append({"role": "assistant", "response": response, "activity": feed.lines})
        except api_client.BackendError as exc:
            feed.fail(str(exc))
            state.messages.append({"role": "assistant", "error": str(exc)})
    st.rerun()
