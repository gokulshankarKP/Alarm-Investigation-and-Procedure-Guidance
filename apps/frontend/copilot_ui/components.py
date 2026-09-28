"""Rendering helpers for one copilot response.

Layout principle: the answer first, one slim status line, and everything else (alarm data,
actions, sources, MCP trace) in four focused tabs.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

import streamlit as st

SEVERITY_LABEL = {"critical": "🔴 Critical", "high": "🟠 High", "medium": "🟡 Medium", "low": "🔵 Low"}
STATUS_LABEL = {
    "success": "✅ OK",
    "error": "❌ Error",
    "invalid_input": "⛔ Invalid input",
    "unavailable": "🚫 Unavailable",
    "timeout": "⏱️ Timeout",
    "skipped": "⏭️ Skipped",
}
VERDICT_LABEL = {"consistent": "✅ Consistent", "inconsistent": "❌ Conflicts with documents", "not_covered": "❔ Not covered"}
URGENCY = [("immediate", "Immediate"), ("short_term", "Short term"), ("follow_up", "Follow-up")]

CSS = """
<style>
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {visibility: hidden; height: 0;}
.block-container {padding-top: 1.6rem; padding-bottom: 5rem; max-width: 1180px;}
h1, h2, h3, h4 {letter-spacing: -0.01em;}
.app-title {font-size: 1.55rem; font-weight: 650; margin: 0;}
.app-subtitle {color: #64748b; font-size: 0.92rem; margin: 0.15rem 0 1.2rem 0;}
.badges {display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 0.6rem 0;}
.badge {display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.76rem; font-weight: 500;
        background: #f1f5f9; color: #334155; border: 1px solid #e2e8f0; white-space: nowrap;}
.badge.ok {background: #ecfdf5; color: #047857; border-color: #a7f3d0;}
.badge.warn {background: #fffbeb; color: #b45309; border-color: #fde68a;}
.badge.bad {background: #fef2f2; color: #b91c1c; border-color: #fecaca;}
.badge.info {background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe;}
.dot {display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px;}
.dot.ok {background: #10b981;} .dot.bad {background: #ef4444;} .dot.off {background: #94a3b8;}
.status-row {font-size: 0.85rem; margin: 2px 0; color: #334155;}
.status-row small {color: #64748b;}
.section-label {font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
                color: #64748b; margin: 1rem 0 0.4rem 0;}
.answer {font-size: 1rem; line-height: 1.6; margin: 0.2rem 0 0.4rem 0;}
ol.actions {margin: 0 0 0.6rem 1.1rem; padding: 0;} ol.actions li {margin: 0.25rem 0; line-height: 1.5;}
.callout {border-radius: 8px; padding: 10px 14px; margin: 0.4rem 0 0.6rem 0; font-size: 0.92rem; line-height: 1.5;}
.callout.bad {background: #fef2f2; border: 1px solid #fecaca; color: #7f1d1d;}
.kpi {border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; background: #ffffff; height: 100%;}
.kpi .label {font-size: 0.72rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
.kpi .value {font-size: 1.35rem; font-weight: 650; color: #0f172a; margin-top: 2px;}
.kpi .sub {font-size: 0.8rem; color: #64748b;} .kpi .sub.bad {color: #b91c1c; font-weight: 600;}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {gap: 0.1rem;}
.act {font-size: 0.86rem; line-height: 1.55; color: #1e293b; display: flex; align-items: center; gap: 8px; padding: 1px 0;}
.act.stage {color: #94a3b8; font-size: 0.8rem; margin-top: 4px;}
.act.warn {color: #b45309;}
.act code {font-size: 0.8rem; background: #f8fafc; color: #0f172a; padding: 1px 6px; border-radius: 4px; border: 1px solid #e2e8f0;}
.act .muted {color: #94a3b8; font-size: 0.78rem;}
.mark {font-weight: 700; width: 14px; text-align: center;} .mark.ok {color: #10b981;} .mark.bad {color: #ef4444;}
.spin.small {width: 10px; height: 10px; margin: 0 2px;}
.activity-title {font-weight: 600; font-size: 0.92rem; margin-bottom: 4px; display: flex; align-items: center; gap: 8px;}
.spin {width: 12px; height: 12px; border: 2px solid #cbd5e1; border-top-color: #2563eb; border-radius: 50%;
       display: inline-block; animation: spin 0.8s linear infinite;}
@keyframes spin {to {transform: rotate(360deg);}}
.cite {display: inline-block; font-size: 0.72rem; padding: 0 6px; border-radius: 4px; background: #f1f5f9;
       color: #475569; margin-left: 4px; font-family: ui-monospace, monospace;}
[data-testid="stMetricValue"] {font-size: 1.35rem;}
[data-testid="stChatMessage"] {padding: 0.9rem 1rem;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badges(items: list[tuple[str, str]]) -> None:
    """Render (text, kind) badges; kind in {"", ok, warn, bad, info}."""
    spans = "".join(f'<span class="badge {kind}">{html.escape(text)}</span>' for text, kind in items)
    st.markdown(f'<div class="badges">{spans}</div>', unsafe_allow_html=True)


def section(label: str) -> None:
    st.markdown(f'<div class="section-label">{html.escape(label)}</div>', unsafe_allow_html=True)


def cites(refs: list[str | None]) -> str:
    return "".join(f'<span class="cite">{html.escape(r)}</span>' for r in refs if r)


# -- answer -----------------------------------------------------------------------------------


def render_status_line(resp: dict[str, Any]) -> None:
    conf = resp.get("confidence", "low")
    tools = [t for t in resp.get("tool_trace", []) if t["tool"] != "tools/list"]
    failed = [t for t in tools if t["status"] != "success"]
    llm = resp.get("llm", {})
    items = [
        (resp.get("intent", "").replace("_", " ").capitalize(), "info"),
        (f"Confidence: {conf}", {"high": "ok", "medium": "warn"}.get(conf, "bad")),
        (f"{len(tools)} tool calls" + (f" · {len(failed)} failed" if failed else ""), "bad" if failed else ""),
        (f"{len(resp.get('citations', []))} sources", ""),
        (llm.get("model") if llm.get("used") else "Rule-based answer", ""),
        (f"{resp.get('timings_ms', {}).get('total', 0) / 1000:.1f}s", ""),
    ]
    if resp.get("degraded"):
        items.append(("Degraded", "warn"))
    badges(items)


def _inline(text: str) -> str:
    """Escape text and turn [T#]/[S#] references into small citation pills."""
    return re.sub(r"\[((?:S|T)\d+)\]", lambda m: cites([m.group(1)]), html.escape(text))


def render_answer(resp: dict[str, Any]) -> None:
    """Concise answer: summary, top actions, conflicts. Full detail lives in the tabs."""
    render_status_line(resp)
    st.markdown(f'<div class="answer">{_inline(resp.get("summary", ""))}</div>', unsafe_allow_html=True)

    actions = resp.get("recommended_actions", [])
    top = [a for a in actions if a["urgency"] == "immediate"][:3] or actions[:3]
    if top:
        section("Immediate actions" if top[0]["urgency"] == "immediate" else "Recommended actions")
        items = "".join(f"<li>{html.escape(a['action'])} {cites(a['citations'])}</li>" for a in top)
        st.markdown(f'<ol class="actions">{items}</ol>', unsafe_allow_html=True)
    for f in resp.get("consistency_findings", []):
        if f["verdict"] == "inconsistent":
            st.markdown(
                f'<div class="callout bad"><b>Do not follow</b> the system recommendation "{html.escape(f["api_recommendation"])}". '
                f"{html.escape(f['explanation'])} {cites(f['citations'])}</div>",
                unsafe_allow_html=True,
            )
    more = max(0, len(actions) - len(top)) + len(resp.get("likely_causes", [])) + len(resp.get("procedures", []))
    if more:
        st.caption(f"Likely causes, {len(actions)} actions and applicable procedures are in **Causes & actions** below.")

    notes = resp.get("warnings", [])
    if notes:
        with st.expander(f"Notes ({len(notes)})", icon="⚠️" if resp.get("degraded") else "ℹ️"):
            for note in notes:
                st.markdown(f"- {note}")


def kpi_cards(cards: list[tuple[str, str, str, str]]) -> None:
    """Row of (label, value, sub-text, kind) cards; kind in {"", bad}."""
    cols = st.columns(len(cards))
    for col, (label, value, sub, kind) in zip(cols, cards, strict=True):
        col.markdown(
            f'<div class="kpi"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div>'
            f'<div class="sub {kind}">{html.escape(sub)}</div></div>',
            unsafe_allow_html=True,
        )


# -- overview (alarm data) ------------------------------------------------------------------


def render_overview(resp: dict[str, Any]) -> None:
    panel = resp.get("alarm_panel", {})
    if not any(panel.get(k) for k in ("assets", "active_alarms", "historical_summary", "priority_scores", "kpis")):
        st.info("No alarm data for this question: a document-only answer, or the alarm system was unavailable.")
        return

    active = panel.get("active_alarms", [])
    scores = panel.get("priority_scores", [])
    hist = panel.get("historical_summary")
    asset = (panel.get("assets") or [None])[0]
    critical = sum(1 for a in active if a["severity"] == "critical")
    cards = []
    if asset:
        cards.append(("Asset", asset["asset_id"], f"{asset['asset_name']} · crit. {asset['criticality']}", ""))
    cards.append(("Active alarms", str(len(active)), f"{critical} critical" if critical else "none critical", "bad" if critical else ""))
    if scores:
        cards.append(
            ("Top priority", f"{scores[0]['priority_score']:.0f}/100", f"{scores[0]['alarm_code']} on {scores[0]['asset_id']}", "")
        )
    elif focus := panel.get("focus_alarm"):
        cards.append(("Focus alarm", focus["alarm_code"], f"{focus['severity']} · {focus['asset_id']}", ""))
    if hist:
        cards.append(("Alarms in window", str(hist["count"]), f"since {hist['start'][:10]}", ""))
    kpi_cards(cards)

    if active:
        section("Active alarms")
        st.dataframe(
            [
                {
                    "Severity": SEVERITY_LABEL.get(a["severity"], a["severity"]),
                    "Alarm": a["alarm_code"],
                    "Description": a["alarm_name"],
                    "Asset": a["asset_id"],
                    "Acknowledged": "Yes" if a["acknowledged"] else "No",
                    "Minutes": round(a["duration_minutes"]),
                }
                for a in active
            ],
            hide_index=True,
            width="stretch",
        )
    if scores:
        section("Priority ranking")
        st.dataframe(
            [
                {
                    "Alarm": s["alarm_code"],
                    "Asset": s["asset_id"],
                    "Score": s["priority_score"],
                    "Band": s["priority_band"].capitalize(),
                    "Main drivers": ", ".join(f"{c['factor'].replace('_', ' ')} {c['points']:.0f}" for c in s["components"][:3]),
                }
                for s in scores
            ],
            hide_index=True,
            width="stretch",
            column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f")},
        )

    has_chart = bool(hist and hist.get("by_code"))
    has_side = bool(panel.get("correlation_insights") or panel.get("related_assets"))
    left, right = st.columns(2, gap="large") if has_chart and has_side else (st.container(), st.container())
    with left:
        if hist and hist.get("by_code"):
            section(f"Alarm history ({hist['start'][:10]} → {hist['end'][:10]})")
            st.bar_chart({code: count for code, count in hist["by_code"][:8]}, horizontal=True, height=240)
            for t in (panel.get("trend") or {}).values():
                st.caption(f"Trend: **{t['direction']}** ({t['first_half_avg']} → {t['second_half_avg']} per week)")
    with right:
        if insights := panel.get("correlation_insights"):
            section("Correlation findings")
            for insight in insights[:4]:
                st.markdown(f"- {insight}")
        if related := panel.get("related_assets"):
            section("Related assets")
            st.markdown(" ".join(f"`{r['asset_id']}` {r['relationship'].replace('_', ' ')} ·" for r in related).rstrip(" ·"))
    if rat := panel.get("rationalization"):
        section("Rationalization candidates")
        st.dataframe(
            [
                {
                    "Alarm": r["alarm_code"],
                    "Asset": r["asset_id"],
                    "Reasons": ", ".join(r["reasons"]).replace("_", " "),
                    "Occurrences": r["occurrences"],
                }
                for r in rat[:5]
            ],
            hide_index=True,
            width="stretch",
        )
    for k in panel.get("kpis", []):
        if "result" in k:
            st.metric(
                k["calculation_type"].replace("_", " ").capitalize(),
                f"{k['result']['value']} {k['result']['unit']}",
                f"target {k['result']['target']}",
                delta_color="off",
            )


# -- actions --------------------------------------------------------------------------------


def render_actions(resp: dict[str, Any]) -> None:
    actions = resp.get("recommended_actions", [])
    if actions:
        for key, label in URGENCY:
            group = [a for a in actions if a["urgency"] == key]
            if group:
                section(label)
                for a in group:
                    st.markdown(f"- {html.escape(a['action'])} {cites(a['citations'])}", unsafe_allow_html=True)
    if causes := resp.get("likely_causes"):
        section("Likely causes")
        for i, c in enumerate(causes, start=1):
            st.markdown(f"{i}. {html.escape(c['cause'])} {cites(c['evidence'])}", unsafe_allow_html=True)
    if findings := resp.get("consistency_findings"):
        section("System recommendations vs documents")
        st.dataframe(
            [
                {
                    "Verdict": VERDICT_LABEL[f["verdict"]],
                    "API recommendation": f["api_recommendation"],
                    "Evidence": ", ".join(f["citations"]) or "-",
                }
                for f in findings
            ],
            hide_index=True,
            width="stretch",
        )
    if procs := resp.get("procedures"):
        section("Applicable procedures")
        for p in procs:
            st.markdown(
                f"- **{p['doc_id']} {p.get('section') or ''}**: {html.escape(p['reason'])} {cites([p.get('citation')])}",
                unsafe_allow_html=True,
            )
    if not any(resp.get(k) for k in ("likely_causes", "recommended_actions", "consistency_findings", "procedures")):
        st.info("No structured causes or actions for this answer.")


# -- sources --------------------------------------------------------------------------------


def render_sources(resp: dict[str, Any]) -> None:
    retrieval = resp.get("retrieval", {})
    if retrieval.get("low_confidence"):
        st.warning(f"Low-confidence retrieval: {retrieval.get('reason') or 'the documents may not cover this question'}.")
    for q in resp.get("quarantined_sources", []):
        st.error(
            f"**Quarantined:** {q['doc_id']} ({q['title']}): possible prompt injection, withheld from the model. "
            f"Signals: {', '.join(q['signals'])}."
        )
    citations = resp.get("citations", [])
    if not citations:
        st.info("No document sources were used.")
    for c in citations:
        trust = "controlled" if c["trust_level"] == "controlled" else "UNTRUSTED"
        mark = "●" if c["cited"] else "○"
        with st.expander(
            f"{mark} {c['id']} · {c['doc_id']} {c['section']} · {c['title']}" + ("" if trust == "controlled" else " · ⚠️ untrusted")
        ):
            badges(
                [
                    (c["doc_type"].replace("_", " "), "info"),
                    (f"rev {c['revision']}", ""),
                    (trust, "ok" if trust == "controlled" else "bad"),
                    (f"similarity {c['similarity']:.2f}", ""),
                    *[(code, "") for code in c["matched_alarm_codes"]],
                ]
            )
            st.caption(c["heading_path"])
            st.markdown(c["excerpt"])
    if citations:
        st.caption("● cited in the answer · ○ retrieved as supporting context")


# -- MCP trace ------------------------------------------------------------------------------


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def render_trace(resp: dict[str, Any], key: str) -> None:
    trace = resp.get("tool_trace", [])
    if not trace:
        st.info("No MCP calls were made (MCP server unavailable, or not needed for this question).")
        return
    st.caption(f"Trace ID `{resp.get('trace_id')}` · propagated to the MCP server and the Alarm API")
    st.dataframe(
        [
            {
                "Step": f"T{t['step']}",
                "Tool": t["tool"],
                "Status": STATUS_LABEL.get(t["status"], t["status"]),
                "Duration (ms)": round(t["duration_ms"]),
                "Retries": len(t["retries"]),
                "Purpose": t["purpose"],
            }
            for t in trace
        ],
        hide_index=True,
        width="stretch",
    )
    options = {f"T{t['step']} · {t['tool']}": t for t in trace}
    choice = st.selectbox("Inspect a call", list(options), index=min(1, len(options) - 1), key=f"trace-{key}")
    call = options[choice]
    if call.get("error"):
        st.error(f"{call['error'].get('code', 'ERROR')}: {call['error'].get('message', '')}")
    if call["retries"]:
        st.warning("Retried: " + "; ".join(call["retries"]))
    left, right = st.columns(2)
    with left:
        section("Request")
        st.code(_json(call["arguments"]), language="json")
        if call["api_calls"]:
            section("Upstream API calls")
            st.code(_json(call["api_calls"]), language="json")
    with right:
        section("Response")
        st.code(_json(call["result"])[:20000] if call["result"] is not None else "null", language="json")


def render_details(resp: dict[str, Any], key: str) -> None:
    tabs = st.tabs(
        ["Overview", "Causes & actions", f"Sources ({len(resp.get('citations', []))})", f"Trace ({len(resp.get('tool_trace', []))})", "Raw"]
    )
    with tabs[0]:
        render_overview(resp)
    with tabs[1]:
        render_actions(resp)
    with tabs[2]:
        render_sources(resp)
    with tabs[3]:
        render_trace(resp, key)
    with tabs[4]:
        st.json(resp, expanded=False)
