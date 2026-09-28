"""Rendering helpers for one copilot response."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

STATUS_ICON = {"success": "✅", "error": "❌", "invalid_input": "⛔", "unavailable": "🚫", "timeout": "⏱️", "skipped": "⏭️"}
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
VERDICT_ICON = {"consistent": "✅", "inconsistent": "❌", "not_covered": "❔"}
URGENCY_LABEL = {"immediate": "🔴 Immediate", "short_term": "🟠 Short term", "follow_up": "🔵 Follow-up"}


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def render_header(resp: dict[str, Any]) -> None:
    llm = resp.get("llm", {})
    llm_text = (
        f"{llm.get('model')} ({'used' if llm.get('used') else 'fallback composer'})"
        if llm.get("provider") != "none"
        else "disabled (deterministic composer)"
    )
    conf = {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 low"}.get(resp.get("confidence"), resp.get("confidence"))
    cols = st.columns(5)
    cols[0].caption(f"**Intent**  \n{resp.get('intent')} · {resp.get('intent_method')}")
    cols[1].caption(f"**Confidence**  \n{conf}")
    ok = sum(1 for t in resp.get("tool_trace", []) if t["status"] == "success" and t["tool"] != "tools/list")
    total = sum(1 for t in resp.get("tool_trace", []) if t["tool"] != "tools/list")
    cols[2].caption(f"**MCP tools**  \n{ok}/{total} succeeded")
    cols[3].caption(f"**LLM**  \n{llm_text}")
    cols[4].caption(f"**Time**  \n{resp.get('timings_ms', {}).get('total', 0) / 1000:.1f}s · trace `{resp.get('trace_id')}`")
    if resp.get("degraded"):
        st.warning("Degraded answer: some sources or tools failed. See warnings and the MCP trace.", icon="⚠️")
    for w in resp.get("warnings", []):
        st.caption(f"⚠️ {w}")


def render_alarm_panel(resp: dict[str, Any]) -> None:
    panel = resp.get("alarm_panel", {})
    if not any(panel.get(k) for k in ("assets", "active_alarms", "historical_summary", "priority_scores", "kpis")):
        st.info("No alarm data for this question (document-only answer or alarm system unavailable).")
        return
    if assets := panel.get("assets"):
        cols = st.columns(min(len(assets), 4))
        for col, a in zip(cols, assets[:4], strict=False):
            col.metric(a["asset_id"], a["asset_name"], f"{a['site']} · {a['unit']} · crit {a['criticality']}", delta_color="off")
    if focus := panel.get("focus_alarm"):
        st.markdown(
            f"**Focus alarm:** {SEVERITY_ICON.get(focus['severity'], '')} `{focus['alarm_code']}` on "
            f"**{focus['asset_id']}** ({focus['alarm_id']}, {focus['severity']}, {focus['status']})"
        )
    active = panel.get("active_alarms", [])
    st.markdown(f"**Active alarms ({len(active)})**")
    if active:
        st.dataframe(
            [
                {
                    "sev": SEVERITY_ICON.get(a["severity"], "") + " " + a["severity"],
                    "asset": a["asset_id"],
                    "code": a["alarm_code"],
                    "name": a["alarm_name"],
                    "ack": "yes" if a["acknowledged"] else "NO",
                    "minutes": a["duration_minutes"],
                    "started": a["start_time"],
                    "id": a["alarm_id"],
                }
                for a in active
            ],
            hide_index=True,
            width="stretch",
        )
    if scores := panel.get("priority_scores"):
        st.markdown("**Dynamic priority scores**")
        st.dataframe(
            [
                {
                    "alarm": s["alarm_id"],
                    "asset": s["asset_id"],
                    "code": s["alarm_code"],
                    "score": s["priority_score"],
                    "band": s["priority_band"],
                    **{c["factor"]: c["points"] for c in s["components"]},
                }
                for s in scores
            ],
            hide_index=True,
            width="stretch",
        )
    if hist := panel.get("historical_summary"):
        c1, c2 = st.columns(2)
        c1.metric("Alarms in window", hist["count"])
        if hist.get("summary"):
            c2.caption("KPIs: " + ", ".join(f"{k}={v}" for k, v in hist["summary"].items()))
        st.bar_chart({code: count for code, count in hist["by_code"]}, horizontal=True)
    if trend := panel.get("trend"):
        for metric, t in trend.items():
            st.caption(f"Trend {metric}: **{t['direction']}** ({t['first_half_avg']} → {t['second_half_avg']} per bucket)")
    if insights := panel.get("correlation_insights"):
        st.markdown("**Correlation insights**")
        for i in insights:
            st.markdown(f"- {i}")
    if related := panel.get("related_assets"):
        st.markdown("**Related assets:** " + ", ".join(f"`{r['asset_id']}` ({r['relationship']})" for r in related))
    if rat := panel.get("rationalization"):
        st.markdown("**Rationalization candidates**")
        st.dataframe(
            [
                {
                    "asset": r["asset_id"],
                    "code": r["alarm_code"],
                    "reasons": ", ".join(r["reasons"]),
                    "occurrences": r["occurrences"],
                    "max/7d": r["max_occurrences_in_7_days"],
                }
                for r in rat
            ],
            hide_index=True,
            width="stretch",
        )
    for k in panel.get("kpis", []):
        if "result" in k:
            st.metric(
                k["calculation_type"], f"{k['result']['value']} {k['result']['unit']}", f"target {k['result']['target']}", delta_color="off"
            )
        elif "flood_windows" in k:
            st.caption(f"Floods: {k['flood_count']} · {k['percent_time_in_flood']}% time in flood")


def render_causes_actions(resp: dict[str, Any]) -> None:
    if causes := resp.get("likely_causes"):
        st.markdown("**Likely causes**")
        for c in causes:
            st.markdown(f"- {c['cause']} " + " ".join(f"`{e}`" for e in c["evidence"]))
    if actions := resp.get("recommended_actions"):
        st.markdown("**Recommended actions**")
        st.dataframe(
            [
                {"urgency": URGENCY_LABEL.get(a["urgency"], a["urgency"]), "action": a["action"], "evidence": ", ".join(a["citations"])}
                for a in actions
            ],
            hide_index=True,
            width="stretch",
        )
    if findings := resp.get("consistency_findings"):
        st.markdown("**API recommendations vs documents**")
        for f in findings:
            st.markdown(
                f"{VERDICT_ICON[f['verdict']]} **{f['verdict'].replace('_', ' ')}**: {f['api_recommendation']}  \n"
                f"<small>{f['explanation']} {' '.join(f['citations'])}</small>",
                unsafe_allow_html=False,
            )
    if procs := resp.get("procedures"):
        st.markdown("**Applicable procedures**")
        for p in procs:
            st.markdown(f"- **{p['doc_id']} {p.get('section') or ''}**: {p['reason']} `{p.get('citation') or ''}`")
    if not any(resp.get(k) for k in ("likely_causes", "recommended_actions", "consistency_findings", "procedures")):
        st.info("No structured causes or actions for this answer.")


def render_citations(resp: dict[str, Any]) -> None:
    citations = resp.get("citations", [])
    retrieval = resp.get("retrieval", {})
    if retrieval.get("low_confidence"):
        st.warning(f"Low-confidence retrieval: {retrieval.get('reason') or 'documents may not cover this question'}")
    if not citations:
        st.info("No document sources were used.")
    for c in citations:
        trust = "🔒 controlled" if c["trust_level"] == "controlled" else "⚠️ UNTRUSTED"
        cited = "cited" if c["cited"] else "retrieved"
        with st.expander(f"[{c['id']}] {c['doc_id']} rev {c['revision']} {c['section']} · {c['title']} · {trust} · {cited}"):
            st.caption(
                f"{c['doc_type']} · status {c['status']} · score {c['score']:.4f} · similarity {c['similarity']:.3f}"
                + (f" · exact codes {', '.join(c['matched_alarm_codes'])}" if c["matched_alarm_codes"] else "")
                + f" · `{c['source_path']}`"
            )
            st.markdown(f"*{c['heading_path']}*")
            st.text(c["excerpt"])
    for q in resp.get("quarantined_sources", []):
        with st.expander(f"🛑 Quarantined: {q['doc_id']} · {q['title']} ({q['trust_level']})"):
            st.error(q["reason"])
            st.caption("Signals: " + ", ".join(q["signals"]))
    if queries := retrieval.get("queries"):
        with st.expander(f"Retrieval queries ({len(queries)})"):
            st.dataframe(
                [
                    {
                        "purpose": q["purpose"],
                        "query": q["query"][:120],
                        "top_similarity": q["top_similarity"],
                        "low_confidence": q["low_confidence"],
                        "filters": json.dumps(q["filters"]),
                    }
                    for q in queries
                ],
                hide_index=True,
                width="stretch",
            )


def render_trace(resp: dict[str, Any]) -> None:
    trace = resp.get("tool_trace", [])
    if not trace:
        st.error("No MCP calls were made (MCP server unavailable or not needed for this question).")
        return
    st.dataframe(
        [
            {
                "step": f"T{t['step']}",
                "status": f"{STATUS_ICON.get(t['status'], '')} {t['status']}",
                "tool": t["tool"],
                "purpose": t["purpose"],
                "ms": t["duration_ms"],
                "api attempts": t["attempts"],
                "retries": len(t["retries"]),
            }
            for t in trace
        ],
        hide_index=True,
        width="stretch",
    )
    for t in trace:
        label = f"T{t['step']} {STATUS_ICON.get(t['status'], '')} {t['tool']} · {t['duration_ms']:.0f} ms"
        if t["retries"]:
            label += f" · 🔁 {len(t['retries'])} retr{'y' if len(t['retries']) == 1 else 'ies'}"
        with st.expander(label):
            st.caption(f"{t['purpose']} · server `{t['server']}` · trace `{t['trace_id']}` · started {t['started_at']}")
            if t.get("error"):
                st.error(_json(t["error"]))
            if t["retries"]:
                st.warning("Retries: " + "; ".join(t["retries"]))
            c1, c2 = st.columns(2)
            c1.markdown("**Request (MCP arguments)**")
            c1.code(_json(t["arguments"]), language="json")
            if t["api_calls"]:
                c1.markdown("**Upstream API calls**")
                c1.code(_json(t["api_calls"]), language="json")
            c2.markdown("**Response (structured content)**")
            c2.code(_json(t["result"])[:20000] if t["result"] is not None else "null", language="json")
    if errors := resp.get("errors"):
        st.markdown("**Errors**")
        st.code(_json(errors), language="json")
