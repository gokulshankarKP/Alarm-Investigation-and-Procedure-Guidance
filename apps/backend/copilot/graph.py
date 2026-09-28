"""LangGraph orchestration of the alarm-investigation workflow.

    understand -> [out_of_scope] ----------------------------------------------> synthesize -> guard
               -> [document_question | MCP unavailable] ------------> retrieve -^
               -> resolve_scope -> collect_alarms -> analyze -> recommend -> retrieve
                                                      retrieve -> check_consistency -> synthesize -> guard

The chain is data-driven rather than hard-coded: which tools run, with which arguments,
depends on the detected intent, the entities, and the outputs of earlier tools (resolved
asset ids feed alarm retrieval; the chosen focus alarm feeds priority scoring and
recommendations; alarm codes and asset classes feed the RAG filters).

Conversation memory: a checkpointer keyed by ``conversation_id`` keeps ``context`` (last
assets / alarm codes / site) and ``history``, enabling follow-ups such as
"Which procedure applies to this alarm?".
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from copilot import consistency, guard
from copilot.config import CopilotSettings
from copilot.intent import detect_intent
from copilot.llm import LLMClient, LLMError
from copilot.mcp_gateway import McpToolSession
from copilot.retrieval_plan import plan_queries, run_retrieval
from copilot.schemas import Action, Cause, Citation, ConsistencyFinding, ProcedureRef, ToolCallRecord
from copilot.synthesis import (
    SEVERITY_ORDER,
    build_digest,
    build_user_prompt,
    compose_deterministic,
    generate_answer,
    render_markdown,
)
from rag.retrieval import Retriever
from shared.observability import log_event

logger = logging.getLogger(__name__)

ASSET_INTENTS = {
    "alarm_investigation",
    "active_alarm_triage",
    "recurring_alarm_analysis",
    "related_assets",
    "recommendation_consistency",
    "priority_ranking",
    "procedure_lookup",
    "kpi_analysis",
}
RECOMMEND_INTENTS = {
    "alarm_investigation",
    "active_alarm_triage",
    "recurring_alarm_analysis",
    "related_assets",
    "recommendation_consistency",
    "priority_ranking",
    "procedure_lookup",
}


@dataclass
class Deps:
    settings: CopilotSettings
    llm: LLMClient
    retriever: Retriever | None
    tools: McpToolSession | None
    mcp_error: str | None = None


class CopilotState(TypedDict, total=False):
    # persisted across turns (checkpointed per conversation)
    context: dict[str, Any]
    history: list[dict[str, str]]
    # per turn (reset by the service on every request)
    question: str
    trace_id: str
    intent: dict[str, Any]
    time_window: dict[str, str]
    scope: dict[str, Any]
    evidence: dict[str, Any]
    focus_alarm: dict[str, Any] | None
    retrieval: dict[str, Any]
    findings: list[dict[str, Any]]
    answer: dict[str, Any]
    warnings: list[str]
    errors: list[dict[str, Any]]
    llm_used: bool


def _iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _tools(runtime: Runtime[Deps]) -> McpToolSession:
    """MCP session for nodes that only run when MCP is connected (see ``route_after_understand``)."""
    if runtime.context.tools is None:
        raise RuntimeError("MCP tool session unavailable")
    return runtime.context.tools


def _note_failure(state: Mapping[str, Any], rec: ToolCallRecord) -> dict[str, Any]:
    """Partial-failure bookkeeping: record the error and a user-visible warning."""
    err = rec.error or {}
    warning = f"{rec.tool} {rec.status}: {err.get('code', '')} {str(err.get('message', ''))[:160]}".strip()
    return {
        "warnings": state.get("warnings", []) + [warning],
        "errors": state.get("errors", []) + [{"step": rec.step, "tool": rec.tool, "status": rec.status, **err}],
    }


def _merge(state: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in updates.items():
        if key == "evidence":
            out[key] = {**state.get("evidence", {}), **value}
        else:
            out[key] = value
    return out


# -- nodes ----------------------------------------------------------------------------------


async def understand(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    result = await detect_intent(
        state["question"], deps.llm, mode=deps.settings.intent_mode, context=state.get("context"), history=state.get("history")
    )
    end = deps.settings.now()
    days = result.entities.lookback_days or deps.settings.default_lookback_days
    warnings = list(state.get("warnings", []))
    if result.llm_error:
        warnings.append(f"Intent LLM unavailable, used rule-based detection ({result.llm_error[:120]})")
    if result.used_context:
        warnings.append("Follow-up question: reused asset/alarm context from the previous turn")
    return {
        "intent": result.model_dump(),
        "warnings": warnings,
        "time_window": {"start": _iso(end - timedelta(days=days)), "end": _iso(end), "lookback_days": str(days)},
    }


def route_after_understand(state: CopilotState, runtime: Runtime[Deps]) -> str:
    intent = state["intent"]["intent"]
    if intent == "out_of_scope":
        return "synthesize"
    if intent == "document_question" or runtime.context.tools is None:
        return "retrieve"
    return "resolve_scope"


async def resolve_scope(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    tools = _tools(runtime)
    ent = state["intent"]["entities"]
    updates: dict[str, Any] = {}
    site = ent["sites"][0] if ent["sites"] else None
    unit = ent["units"][0] if ent["units"] else None
    filters = {k: v for k, v in {"site": site, "unit": unit}.items() if v}

    queries: list[tuple[str, bool]] = [(q, True) for q in ent["asset_ids"] + ent["asset_names"]]
    if not queries and ent["asset_classes"] and state["intent"]["intent"] != "priority_ranking":
        queries = [(ent["asset_classes"][0].replace("_", " "), False)]
    assets: dict[str, dict] = {}
    searches = []
    for query, specific in queries[:4]:
        rec = await tools.call(
            "search_assets", {"query": query, "limit": 5, **filters}, purpose=f"Resolve '{query}' to an asset identifier"
        )
        if rec.status != "success":
            updates.update(_note_failure({**state, **updates}, rec))
            continue
        results = rec.result.get("results", [])
        searches.append({"ref": f"T{rec.step}", "query": query, "data": rec.result})
        if not results:
            updates["warnings"] = updates.get("warnings", state.get("warnings", [])) + [f"No asset matches '{query}'"]
            continue
        chosen = results[:1] if specific else [r for r in results if r["match_score"] >= 0.75][:3]
        if specific and not results[0].get("exact_match") and results[0]["match_score"] < 0.75:
            updates["warnings"] = updates.get("warnings", state.get("warnings", [])) + [
                f"'{query}' only partially matches {results[0]['asset_id']} ({results[0]['asset_name']})"
            ]
        for r in chosen:
            assets.setdefault(r["asset_id"], r)

    evidence: dict[str, Any] = {"asset_search": searches}
    related: list[dict] = []
    if assets:
        primary = next(iter(assets))
        rec = await tools.call("get_asset_metadata", {"asset_id": primary}, purpose=f"Asset context and related assets for {primary}")
        if rec.status == "success":
            evidence["asset_metadata"] = {"ref": f"T{rec.step}", "data": rec.result}
            related = rec.result.get("related_assets", [])
        else:
            updates.update(_note_failure({**state, **updates}, rec))
    elif state["intent"]["intent"] in ASSET_INTENTS and not (site or unit or ent["alarm_codes"]):
        updates["warnings"] = updates.get("warnings", state.get("warnings", [])) + [
            "No asset, site or unit could be identified; answering from documents only"
        ]

    first = next(iter(assets.values()), None)
    scope = {
        "assets": list(assets.values()),
        "asset_ids": list(assets),
        "asset_classes": list(dict.fromkeys([a["asset_class"] for a in assets.values()] + ent["asset_classes"])),
        "site": site or (first["site"] if first else None),
        "unit": unit,
        "related_assets": related,
    }
    return {**_merge(state, evidence=evidence), **updates, "scope": scope}


def _scope_args(state: CopilotState) -> dict[str, Any] | None:
    scope, ent = state.get("scope", {}), state["intent"]["entities"]
    if scope.get("asset_ids"):
        return {"asset_ids": scope["asset_ids"][:10]}
    args = {
        k: v for k, v in {"site": ent["sites"][0] if ent["sites"] else None, "unit": ent["units"][0] if ent["units"] else None}.items() if v
    }
    if args:
        return args
    if ent["alarm_codes"]:
        return {"alarm_code": ent["alarm_codes"][0]}
    return None


async def collect_alarms(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    tools = _tools(runtime)
    intent, ent, window = state["intent"]["intent"], state["intent"]["entities"], state["time_window"]
    scope_args = _scope_args(state)
    if scope_args is None:
        return {"focus_alarm": None}
    updates: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    severities = ent["severities"] or None

    active_args = {**scope_args, "status": "active", "page_size": 100, "sort_by": "priority", "sort_order": "asc"}
    if severities and intent == "active_alarm_triage":
        active_args["severities"] = severities
    rec = await tools.call("get_alarms", active_args, purpose="Retrieve currently active alarms")
    active: list[dict] = []
    if rec.status == "success":
        active = rec.result["alarms"]
        evidence["active_alarms"] = {"ref": f"T{rec.step}", "data": active}
    else:
        updates.update(_note_failure(state, rec))

    historical: list[dict] = []
    if intent not in {"active_alarm_triage", "priority_ranking"} or ent["status"] == "historical":
        hist_args = {
            **scope_args,
            "status": "all",
            "start_time": window["start"],
            "end_time": window["end"],
            "page_size": 200,
            "fetch_all_pages": True,
        }
        if severities:
            hist_args["severities"] = severities
        rec = await tools.call("get_alarms", hist_args, purpose=f"Retrieve alarm history for the last {window['lookback_days']} days")
        if rec.status == "success":
            historical = rec.result["alarms"]
            by_code = Counter(a["alarm_code"] for a in historical).most_common()
            evidence["historical_alarms"] = {
                "ref": f"T{rec.step}",
                "data": {
                    "count": len(historical),
                    "start": window["start"],
                    "end": window["end"],
                    "by_code": by_code,
                    "truncated": rec.result.get("truncated", False),
                },
            }
        else:
            updates.update(_note_failure({**state, **updates}, rec))

    return {**_merge(state, evidence=evidence), **updates, "focus_alarm": choose_focus_alarm(intent, ent, active, historical)}


def choose_focus_alarm(intent: str, ent: dict[str, Any], active: list[dict], historical: list[dict]) -> dict | None:
    """Pick the alarm that drives recommendations and procedure retrieval.

    Explicit alarm codes and requested severities narrow the pool. Recurrence questions
    focus on the most frequent (severe) historical code; otherwise the most severe, most
    recent active alarm wins, falling back to history.
    """
    codes, sevs = set(ent["alarm_codes"]), set(ent["severities"])

    def narrow(rows: list[dict]) -> list[dict]:
        rows = [a for a in rows if not codes or a["alarm_code"] in codes]
        return [a for a in rows if not sevs or a["severity"] in sevs]

    def from_history() -> dict | None:
        pool = narrow(historical) or historical
        if not pool:
            return None
        # Recurrence questions without a severity filter are about frequency, not severity.
        frequency_only = intent == "recurring_alarm_analysis" and not sevs
        severe = pool if frequency_only else [a for a in pool if a["severity"] in ("critical", "high")] or pool
        top_code = Counter(a["alarm_code"] for a in severe).most_common(1)[0][0]
        return max((a for a in severe if a["alarm_code"] == top_code), key=lambda a: a["start_time"])

    if intent == "recurring_alarm_analysis" and historical:
        return from_history()
    pool = narrow(active) or ([] if (codes or sevs) and historical else active)
    if pool:
        return min(pool, key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), -_ts(a["start_time"])))
    return from_history()


def _ts(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


async def analyze(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    tools, settings = _tools(runtime), runtime.context.settings
    intent, ent, window = state["intent"]["intent"], state["intent"]["entities"], state["time_window"]
    scope_args = _scope_args(state) or {}
    scope_args.pop("alarm_code", None)
    asset_ids = state.get("scope", {}).get("asset_ids", [])
    tw = {"start_time": window["start"], "end_time": window["end"]}
    jobs: list[tuple[str, str, dict, str]] = []  # (evidence_key, tool, args, purpose)

    if intent in {"alarm_investigation", "recurring_alarm_analysis", "related_assets"} and scope_args:
        kpis = ["alarm_count", "recurring_rate", "avg_ack_delay", "critical_count"]
        args = {**scope_args, **tw, "group_by": ["alarm_code", "alarm_name"], "kpis": kpis}
        if ent["severities"]:
            args["severities"] = ent["severities"]
        jobs.append(("summary", "summarize_alarms", args, "Aggregate alarm KPIs for the window"))
    if intent in {"alarm_investigation", "recurring_alarm_analysis"} and scope_args:
        jobs.append(
            ("trends", "get_alarm_trends", {**scope_args, **tw, "bucket": "weekly", "metrics": ["alarm_count"]}, "Weekly alarm trend")
        )
        jobs.append(
            ("rationalization", "find_rationalization_candidates", {**scope_args, **tw}, "Check for recurring/chattering/stale alarms")
        )
    if intent in {"alarm_investigation", "recurring_alarm_analysis", "related_assets", "active_alarm_triage"} and asset_ids:
        jobs.append(
            (
                "correlation",
                "correlate_alarms",
                {
                    "asset_ids": asset_ids[:5],
                    **tw,
                    "lag_window_minutes": 15,
                    "severity_threshold": "medium",
                    "min_support": 2,
                    "include_related": True,
                },
                "Correlate alarms with related assets (sequences, common causes)",
            )
        )
    if intent == "kpi_analysis" and scope_args:
        kpi = ent.get("kpi") or "alarm_flood_index"
        jobs.append(("kpis", "calculate_alarm_kpi", {"calculation_type": kpi, **scope_args, **tw}, f"Compute KPI {kpi}"))
        if kpi == "alarm_flood_index" and (scope_args.get("site") or scope_args.get("unit") or asset_ids):
            jobs.append(("floods", "analyze_alarm_floods", {**scope_args, **tw}, "Detect alarm flood windows"))

    records = await asyncio.gather(*(tools.call(tool, args, purpose=purpose) for _, tool, args, purpose in jobs))
    evidence: dict[str, Any] = {}
    updates: dict[str, Any] = {}
    for (key, *_), rec in zip(jobs, records, strict=True):
        if rec.status == "success":
            item = {"ref": f"T{rec.step}", "data": rec.result}
            if key == "kpis":
                evidence.setdefault("kpis", []).append(item)
            else:
                evidence[key] = item
        else:
            updates.update(_note_failure({**state, **updates}, rec))

    # Priority scoring: rank active alarms (most severe first) and focus on the highest score.
    focus = state.get("focus_alarm")
    active = (state.get("evidence", {}).get("active_alarms") or {}).get("data", [])
    if intent in {"priority_ranking", "active_alarm_triage", "alarm_investigation"} and active:
        candidates = sorted(active, key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), a["start_time"]))
        candidates = candidates[: settings.max_priority_scoring if intent == "priority_ranking" else 3]
        recs = await asyncio.gather(
            *(
                tools.call(
                    "score_alarm_priority",
                    {"alarm_id": a["alarm_id"]},
                    purpose=f"Dynamic priority score for {a['alarm_code']} on {a['asset_id']}",
                )
                for a in candidates
            )
        )
        scores = []
        for rec in recs:
            if rec.status == "success":
                scores.append({"ref": f"T{rec.step}", "data": rec.result})
            else:
                updates.update(_note_failure({**state, **updates}, rec))
        if scores:
            evidence["priority_scores"] = scores
            # Re-focus on the top-scored alarm unless the user named a specific alarm code.
            if intent == "priority_ranking" or not ent["alarm_codes"] or focus is None:
                best = max(scores, key=lambda s: s["data"]["priority_score"])["data"]
                focus = next((a for a in active if a["alarm_id"] == best["alarm_id"]), focus)
    return {**_merge(state, evidence=evidence), **updates, "focus_alarm": focus}


async def recommend(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    focus = state.get("focus_alarm")
    if not focus or state["intent"]["intent"] not in RECOMMEND_INTENTS:
        return {}
    rec = await _tools(runtime).call(
        "get_operator_recommendations",
        {"alarm_id": focus["alarm_id"], "include_related": True, "include_asset_context": False, "include_historical_pattern": True},
        purpose=f"API recommendations for {focus['alarm_code']} on {focus['asset_id']} ({focus['alarm_id']})",
    )
    if rec.status != "success":
        return _note_failure(state, rec)
    return _merge(state, evidence={"recommendations": {"ref": f"T{rec.step}", "data": rec.result}})


async def retrieve(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    intent, ent = state["intent"]["intent"], state["intent"]["entities"]
    scope, evidence = state.get("scope", {}), state.get("evidence", {})
    warnings = list(state.get("warnings", []))
    if deps.tools is None and intent != "document_question":
        warnings.append(f"Alarm data unavailable (MCP server unreachable): answering from documents only. {deps.mcp_error or ''}".strip())
    if deps.retriever is None:
        warnings.append("Document retrieval unavailable: no RAG index configured")
        return {
            "retrieval": {"low_confidence": True, "citations": [], "quarantined": [], "queries": [], "reason": "retriever unavailable"},
            "warnings": warnings,
        }

    focus = state.get("focus_alarm")
    codes = list(ent["alarm_codes"])
    names: dict[str, str] = {}
    if focus:
        codes = [focus["alarm_code"], *codes]
        names[focus["alarm_code"]] = focus.get("alarm_name", "")
    hist = (evidence.get("historical_alarms") or {}).get("data")
    if intent == "recurring_alarm_analysis" and hist:
        codes += [c for c, _ in hist["by_code"][:2]]  # recurrence: most frequent codes, not current alarms
    else:
        for a in (evidence.get("active_alarms") or {}).get("data", [])[:5]:
            names.setdefault(a["alarm_code"], a.get("alarm_name", ""))
            if a["severity"] in ("critical", "high"):
                codes.append(a["alarm_code"])
        if hist and not codes:
            codes += [c for c, _ in hist["by_code"][:2]]
    recs = [r["action"] for r in ((evidence.get("recommendations") or {}).get("data") or {}).get("recommendations", [])]
    sites = [scope["site"]] if scope.get("site") else list(ent["sites"])
    classes = scope.get("asset_classes") or list(ent["asset_classes"])

    plan = plan_queries(
        state["question"],
        intent,
        sites=sites,
        asset_classes=classes,
        alarm_codes=list(dict.fromkeys(codes)),
        alarm_names=names,
        recommendations=recs,
    )
    try:
        outcome = await run_retrieval(deps.retriever, plan)
    except Exception as exc:
        warnings.append(f"Document retrieval failed: {type(exc).__name__}: {str(exc)[:160]}")
        return {
            "retrieval": {"low_confidence": True, "citations": [], "quarantined": [], "queries": [], "reason": "retrieval error"},
            "warnings": warnings,
            "errors": state.get("errors", []) + [{"stage": "rag", "code": "RETRIEVAL_ERROR", "message": str(exc)[:300]}],
        }
    if outcome.quarantined:
        warnings.append(f"{len(outcome.quarantined)} retrieved passage(s) quarantined as possible prompt injection")
    if outcome.low_confidence:
        warnings.append("Low-confidence retrieval: the documents may not cover this question")
    return {
        "warnings": warnings,
        "retrieval": {
            "low_confidence": outcome.low_confidence,
            "reason": outcome.reason,
            "queries": outcome.queries,
            "citations": [c.model_dump() for c in outcome.citations],
            "quarantined": [q.model_dump() for q in outcome.quarantined],
        },
    }


async def check_consistency(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    rec = (state.get("evidence") or {}).get("recommendations")
    if not rec:
        return {"findings": []}
    citations = [Citation(**c) for c in state["retrieval"].get("citations", [])]
    findings = consistency.evaluate(rec["data"].get("recommendations", []), citations, rec["ref"])
    return {"findings": [f.model_dump() for f in findings]}


async def synthesize(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    deps = runtime.context
    intent = state["intent"]["intent"]
    retrieval = state.get("retrieval") or {"citations": [], "low_confidence": True}
    citations = [Citation(**c) for c in retrieval.get("citations", [])]
    findings = [ConsistencyFinding(**f) for f in state.get("findings", [])]
    evidence = state.get("evidence", {})
    notes = [w for w in state.get("warnings", []) if not w.startswith("Follow-up")]
    warnings = list(state.get("warnings", []))

    answer, llm_used = None, False
    if deps.llm.enabled and intent != "out_of_scope":
        # Controlled sources first; at most 6 excerpts keeps CPU-only inference within minutes.
        prompt = build_user_prompt(
            state["question"],
            intent,
            state.get("time_window"),
            build_digest(evidence),
            citations[:6],
            findings,
            notes,
            state.get("history", []),
        )
        log_event(logger, "synthesis_prompt", chars=len(prompt), approx_tokens=len(prompt) // 4)
        try:
            answer = await generate_answer(deps.llm, prompt, findings, notes)
            llm_used = True
        except LLMError as exc:
            warnings.append(f"LLM answer generation failed; used deterministic composer ({str(exc)[:120]})")
    if answer is None:
        answer = compose_deterministic(
            question=state["question"],
            intent=intent,
            evidence=evidence,
            citations=citations,
            findings=findings,
            low_confidence=retrieval.get("low_confidence", True),
            notes=notes,
        )
    if retrieval.get("low_confidence") and not evidence and answer["confidence"] != "low":
        answer["confidence"] = "low"
    return {"answer": _serialise(answer), "warnings": warnings, "llm_used": llm_used}


def _serialise(answer: dict[str, Any]) -> dict[str, Any]:
    return {k: ([x.model_dump() for x in v] if isinstance(v, list) and v and hasattr(v[0], "model_dump") else v) for k, v in answer.items()}


async def apply_guard(state: CopilotState, runtime: Runtime[Deps]) -> dict[str, Any]:
    answer = dict(state["answer"])
    tools = runtime.context.tools  # may be None when MCP is unavailable
    ok_steps = {r.ref for r in tools.records if r.status == "success"} if tools else set()
    allowed = {c["id"] for c in state.get("retrieval", {}).get("citations", [])} | ok_steps
    warnings = list(state.get("warnings", []))

    summary, unsafe_s, bad_refs_s = guard.sanitize_text(answer["summary"], allowed)
    actions, notes = guard.filter_actions([Action(**a) for a in answer["recommended_actions"]], allowed)
    causes = guard.filter_causes([Cause(**c) for c in answer["likely_causes"]], allowed)
    procedures = _normalise_procedures(
        [ProcedureRef(**p) for p in answer["procedures"]], state.get("retrieval", {}).get("citations", []), allowed
    )
    markdown = answer["answer_markdown"]
    if state["intent"]["intent"] != "out_of_scope":
        # Re-render from the validated structure so the text matches the panels exactly.
        findings = [ConsistencyFinding(**f) for f in state.get("findings", [])]
        workflow_notes = [w for w in state.get("warnings", []) if not w.startswith("Follow-up")]
        markdown = render_markdown(summary, causes, actions, findings, procedures, workflow_notes, answer.get("consistency_notes", ""))
    text, unsafe, bad_refs = guard.sanitize_text(markdown, allowed)
    if unsafe or unsafe_s:
        warnings.append("Safety guard removed statement(s) that advised bypassing protections or similar")
    if bad_refs or bad_refs_s:
        warnings.append(f"Removed {bad_refs + bad_refs_s} citation reference(s) that did not match any evidence")
    warnings.extend(notes)
    if not any(c.evidence for c in causes) and causes:
        warnings.append("Some likely causes have no supporting citation")

    answer.update(
        answer_markdown=text,
        summary=summary,
        recommended_actions=[a.model_dump() for a in actions],
        likely_causes=[c.model_dump() for c in causes],
        procedures=[p.model_dump() for p in procedures],
    )

    # Remember scope for follow-up questions.
    scope, ent, focus = state.get("scope") or {}, state["intent"]["entities"], state.get("focus_alarm")
    context = dict(state.get("context") or {})
    if scope.get("asset_ids") or ent["alarm_codes"] or focus or ent["sites"]:
        context = {
            "asset_ids": scope.get("asset_ids") or ent["asset_ids"],
            "asset_classes": scope.get("asset_classes") or ent["asset_classes"],
            "alarm_codes": list(dict.fromkeys(([focus["alarm_code"]] if focus else []) + ent["alarm_codes"])),
            "sites": [scope["site"]] if scope.get("site") else ent["sites"],
            "focus_alarm_id": focus["alarm_id"] if focus else None,
        }
    max_turns = runtime.context.settings.max_history_turns * 2
    history = (state.get("history") or []) + [
        {"role": "user", "content": state["question"]},
        {"role": "assistant", "content": answer["summary"][:600]},
    ]
    return {
        "answer": answer,
        "warnings": list(dict.fromkeys(warnings)),
        "context": context,
        "history": history[-max_turns:] if max_turns else [],
    }


def _normalise_procedures(procedures: list[ProcedureRef], citations: list[dict], allowed: set[str]) -> list[ProcedureRef]:
    """Map LLM procedure references onto real retrieved citations; drop ones that match none."""
    by_id = {c["id"]: c for c in citations}
    out: list[ProcedureRef] = []
    for p in procedures:
        cite = by_id.get(p.doc_id) or by_id.get(p.citation or "")
        if cite is None:
            cite = next((c for c in citations if c["doc_id"] == p.doc_id), None)
        if cite is None or cite["id"] not in allowed:
            continue
        out.append(
            ProcedureRef(
                doc_id=cite["doc_id"],
                section=cite["section"],
                citation=cite["id"],
                reason=p.reason or f"{cite['title']}: {cite['heading_path'].split(' > ')[-1]}",
            )
        )
    return list({(p.doc_id, p.section): p for p in out}.values())


# -- graph ----------------------------------------------------------------------------------


def build_graph(checkpointer=None):
    graph = StateGraph(CopilotState, context_schema=Deps)
    graph.add_node("understand", understand)
    graph.add_node("resolve_scope", resolve_scope)
    graph.add_node("collect_alarms", collect_alarms)
    graph.add_node("analyze", analyze)
    graph.add_node("recommend", recommend)
    graph.add_node("retrieve", retrieve)
    graph.add_node("check_consistency", check_consistency)
    graph.add_node("synthesize", synthesize)
    graph.add_node("guard", apply_guard)

    graph.add_edge(START, "understand")
    graph.add_conditional_edges(
        "understand", route_after_understand, {"synthesize": "synthesize", "retrieve": "retrieve", "resolve_scope": "resolve_scope"}
    )
    graph.add_edge("resolve_scope", "collect_alarms")
    graph.add_edge("collect_alarms", "analyze")
    graph.add_edge("analyze", "recommend")
    graph.add_edge("recommend", "retrieve")
    graph.add_edge("retrieve", "check_consistency")
    graph.add_edge("check_consistency", "synthesize")
    graph.add_edge("synthesize", "guard")
    graph.add_edge("guard", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
