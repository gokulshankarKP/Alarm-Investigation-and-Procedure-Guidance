"""Copilot service: runs one chat turn end to end and assembles the API response."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from copilot.config import CopilotSettings
from copilot.graph import Deps, build_graph
from copilot.llm import LLMClient, create_llm
from copilot.mcp_gateway import McpGateway, McpUnavailableError
from copilot.schemas import (
    Action,
    AlarmPanel,
    Cause,
    ChatResponse,
    Citation,
    ConsistencyFinding,
    ProcedureRef,
    QuarantinedSource,
    ToolInfo,
)
from rag.retrieval import Retriever
from shared.observability import conversation_id_var, log_event, new_trace_id, trace_id_var

logger = logging.getLogger(__name__)


class CopilotService:
    def __init__(
        self,
        settings: CopilotSettings,
        *,
        retriever: Retriever | None,
        llm: LLMClient | None = None,
        gateway: McpGateway | None = None,
        retriever_error: str | None = None,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.retriever_error = retriever_error
        self.llm = llm or create_llm(settings)
        self.gateway = gateway or McpGateway(settings)
        self.graph = build_graph()

    async def chat(self, message: str, conversation_id: str | None = None) -> ChatResponse:
        conversation_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
        trace_id = new_trace_id("trace")
        t_token, c_token = trace_id_var.set(trace_id), conversation_id_var.set(conversation_id)
        started = time.perf_counter()
        try:
            state: dict[str, Any] = {}
            tools_discovered: list[str] = []
            records = []
            mcp_error = None
            turn: dict[str, Any] = {
                "question": message,
                "trace_id": trace_id,
                "intent": {},
                "scope": {},
                "evidence": {},
                "focus_alarm": None,
                "retrieval": {},
                "findings": [],
                "answer": {},
                "warnings": [],
                "errors": [],
                "llm_used": False,
            }
            config = {"configurable": {"thread_id": conversation_id}}
            try:
                async with self.gateway.connect(trace_id, conversation_id) as tools:
                    tools_discovered = tools.tool_names
                    state = await self.graph.ainvoke(turn, config=config, context=self._deps(tools, None))
                    records = sorted(tools.records, key=lambda r: r.step)
            except McpUnavailableError as exc:
                mcp_error = str(exc)
                log_event(logger, "mcp_unavailable", logging.WARNING, error=mcp_error[:300])
                state = await self.graph.ainvoke(turn, config=config, context=self._deps(None, mcp_error))
            response = self._build_response(state, conversation_id, trace_id, tools_discovered, records, mcp_error)
            response.timings_ms["total"] = round((time.perf_counter() - started) * 1000, 1)
            log_event(
                logger,
                "chat_completed",
                intent=response.intent,
                tools_called=len(records),
                citations=len(response.citations),
                degraded=response.degraded,
                duration_ms=response.timings_ms["total"],
                llm_used=response.llm.get("used"),
            )
            return response
        finally:
            trace_id_var.reset(t_token)
            conversation_id_var.reset(c_token)

    def _deps(self, tools, mcp_error: str | None) -> Deps:
        return Deps(settings=self.settings, llm=self.llm, retriever=self.retriever, tools=tools, mcp_error=mcp_error)

    def _build_response(
        self, state: dict[str, Any], conversation_id: str, trace_id: str, tools_discovered: list[str], records: list, mcp_error: str | None
    ) -> ChatResponse:
        answer = state.get("answer") or {}
        evidence = state.get("evidence") or {}
        retrieval = state.get("retrieval") or {}
        intent = state.get("intent") or {}
        text = answer.get("answer_markdown", "")
        citations = [Citation(**c) for c in retrieval.get("citations", [])]
        for c in citations:
            c.cited = f"[{c.id}]" in text or any(c.id in a.get("citations", []) for a in answer.get("recommended_actions", []))

        panel = AlarmPanel(
            assets=[r for s in evidence.get("asset_search", []) for r in s["data"].get("results", [])[:1]],
            related_assets=(evidence.get("asset_metadata") or {}).get("data", {}).get("related_assets", []),
            active_alarms=(evidence.get("active_alarms") or {}).get("data", []),
            historical_summary=(evidence.get("historical_alarms") or {}).get("data")
            and {
                **evidence["historical_alarms"]["data"],
                "by_code": evidence["historical_alarms"]["data"]["by_code"][:10],
                "summary": (evidence.get("summary") or {}).get("data", {}).get("totals"),
            },
            focus_alarm=state.get("focus_alarm"),
            priority_scores=sorted([p["data"] for p in evidence.get("priority_scores", [])], key=lambda d: -d["priority_score"]),
            correlation_insights=(evidence.get("correlation") or {}).get("data", {}).get("insights", []),
            common_causes=(evidence.get("correlation") or {}).get("data", {}).get("common_cause_candidates", []),
            rationalization=(evidence.get("rationalization") or {}).get("data", {}).get("candidates", [])[:8],
            trend=(evidence.get("trends") or {}).get("data", {}).get("trend"),
            kpis=[k["data"] for k in evidence.get("kpis", [])] + ([evidence["floods"]["data"]] if evidence.get("floods") else []),
        )
        failed = [r for r in records if r.status not in ("success", "skipped")]
        degraded = bool(
            mcp_error
            or failed
            or (not state.get("llm_used") and self.llm.enabled)
            or retrieval.get("reason") in ("retriever unavailable", "retrieval error")
        )
        ent = intent.get("entities", {})
        return ChatResponse(
            conversation_id=conversation_id,
            trace_id=trace_id,
            question=state.get("question", ""),
            intent=intent.get("intent", "unknown"),
            intent_method=intent.get("method", ""),
            entities=ent,
            time_window={k: v for k, v in (state.get("time_window") or {}).items()} or None,
            answer_markdown=text,
            summary=answer.get("summary", ""),
            confidence=answer.get("confidence", "low"),
            likely_causes=[Cause(**c) for c in answer.get("likely_causes", [])],
            recommended_actions=[Action(**a) for a in answer.get("recommended_actions", [])],
            consistency_findings=[ConsistencyFinding(**f) for f in state.get("findings", [])],
            procedures=[ProcedureRef(**p) for p in answer.get("procedures", [])],
            alarm_panel=panel,
            citations=citations,
            quarantined_sources=[QuarantinedSource(**q) for q in retrieval.get("quarantined", [])],
            tools_discovered=tools_discovered,
            tool_trace=records,
            retrieval={k: retrieval.get(k) for k in ("low_confidence", "reason", "queries")},
            warnings=state.get("warnings", []),
            errors=state.get("errors", []) + ([{"stage": "mcp", "code": "MCP_UNAVAILABLE", "message": mcp_error}] if mcp_error else []),
            degraded=degraded,
            llm={"provider": self.llm.provider, "model": self.llm.model, "used": bool(state.get("llm_used"))},
        )

    async def list_tools(self) -> list[ToolInfo]:
        return await self.gateway.list_tools(new_trace_id("tools"))

    async def health(self) -> dict[str, Any]:
        components: dict[str, Any] = {}
        try:
            tools = await self.list_tools()
            components["mcp_server"] = {"status": "ok", "tools": len(tools)}
        except McpUnavailableError as exc:
            components["mcp_server"] = {"status": "unavailable", "error": str(exc)[:200]}
        if self.retriever is None:
            components["rag_index"] = {"status": "unavailable", "error": self.retriever_error}
        else:
            try:
                import asyncio

                components["rag_index"] = {"status": "ok", **(await asyncio.to_thread(self.retriever.ping))}
            except Exception as exc:
                components["rag_index"] = {"status": "unavailable", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        components["llm"] = {"status": "ok" if self.llm.enabled else "disabled", "provider": self.llm.provider, "model": self.llm.model}
        status = "ok" if all(c["status"] in ("ok", "disabled") for c in components.values()) else "degraded"
        return {"status": status, "components": components}
