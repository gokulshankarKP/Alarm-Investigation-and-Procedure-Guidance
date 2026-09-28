"""Orchestration tests: multi-step MCP chains, RAG inside the same workflow, partial failures,
conflicting evidence, degraded modes, conversation memory, LLM output validation."""

import pytest
from conftest import ScriptedLLM

pytestmark = pytest.mark.integration


def steps(resp):
    return [t.tool for t in resp.tool_trace]


async def test_asset_investigation_chain_passes_outputs_between_tools(stack, make_service):
    resp = await make_service().chat("Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.")
    tools = steps(resp)
    assert tools[:4] == ["tools/list", "search_assets", "get_asset_metadata", "get_alarms"]
    by_tool = {t.tool: t for t in resp.tool_trace}
    # search_assets output (asset id) feeds the following calls
    assert by_tool["get_asset_metadata"].arguments == {"asset_id": "BFP-102"}
    assert by_tool["get_alarms"].arguments["asset_ids"] == ["BFP-102"]
    # focus alarm chosen from get_alarms output feeds priority scoring and recommendations
    focus = resp.alarm_panel.focus_alarm
    assert focus["alarm_code"] == "BFP-SUCT-P-LL" and focus["severity"] == "critical"
    assert by_tool["get_operator_recommendations"].arguments["alarm_id"] == focus["alarm_id"]
    # RAG in the same workflow, filtered by the asset/alarm context from MCP
    assert any(c.doc_id == "SOP-BFP-001" for c in resp.citations)
    assert resp.intent == "active_alarm_triage" and not resp.degraded
    assert "[T" in resp.answer_markdown and "[S" in resp.answer_markdown


async def test_priority_ranking_scores_active_alarms(stack, make_service):
    resp = await make_service().chat("Which alarm has the highest priority in EastRefinery, and why?")
    assert steps(resp).count("score_alarm_priority") >= 3
    assert resp.alarm_panel.priority_scores[0]["alarm_code"] == "CMP-SURGE"
    assert resp.alarm_panel.focus_alarm["alarm_code"] == "CMP-SURGE"
    assert any(c.doc_id == "ALM-PHIL-001" for c in resp.citations)


async def test_conflicting_evidence_api_vs_manual(stack, make_service):
    resp = await make_service().chat("Are the API recommendations for BFP-102 consistent with the maintenance manual?")
    verdicts = {f.api_recommendation: f.verdict for f in resp.consistency_findings}
    assert resp.intent == "recommendation_consistency" and verdicts
    assert "consistent" in verdicts.values()


async def test_restart_recommendation_is_flagged_for_vibration_trip(stack, make_service):
    resp = await make_service().chat("Investigate the BFP-VIB-HH vibration trip on BFP-102 and recommended actions")
    bad = [f for f in resp.consistency_findings if f.verdict == "inconsistent"]
    assert bad and "restart" in bad[0].api_recommendation.lower()
    assert {"MM-BFP-003", "SOP-BFP-001"} & {c.doc_id for c in resp.citations if c.id in bad[0].citations}
    assert all("restart the tripped pump after 10 minutes" not in a.action for a in resp.recommended_actions)


async def test_partial_source_failure_degrades_but_answers(stack, make_service):
    stack.inject_fault("/alarms/correlation", status_code=503, count=20)
    resp = await make_service().chat("Why are compressor discharge pressure alarms repeatedly occurring?")
    corr = next(t for t in resp.tool_trace if t.tool == "correlate_alarms")
    assert corr.status == "error" and corr.error["code"] == "UPSTREAM_UNAVAILABLE"
    assert resp.degraded and any("correlate_alarms" in w for w in resp.warnings)
    assert resp.citations and resp.answer_markdown  # still answered from other tools + documents
    assert any(t.tool == "summarize_alarms" and t.status == "success" for t in resp.tool_trace)


async def test_mcp_down_falls_back_to_documents(copilot_settings, memory_retriever):
    from copilot.llm import NullLLM
    from copilot.service import CopilotService

    settings = copilot_settings.model_copy(update={"mcp_server_url": "http://127.0.0.1:1/mcp"})
    resp = await CopilotService(settings, retriever=memory_retriever, llm=NullLLM()).chat(
        "Which operating procedure applies to BFP-VIB-HH?"
    )
    assert resp.degraded and resp.tool_trace == [] and resp.errors[-1]["code"] == "MCP_UNAVAILABLE"
    assert any(c.doc_id == "SOP-BFP-001" for c in resp.citations)
    assert any("MCP server unreachable" in w for w in resp.warnings)


async def test_retriever_failure_degrades_to_tool_only_answer(stack, make_service):
    class Broken:
        def search(self, *a, **k):
            raise ConnectionError("vector store down")

    resp = await make_service(retriever=Broken()).chat("Show active alarms for K-202")
    assert resp.citations == [] and any("Document retrieval failed" in w for w in resp.warnings)
    assert resp.alarm_panel.active_alarms


async def test_out_of_scope_calls_no_alarm_tools(stack, make_service):
    resp = await make_service().chat("What is the capital of France?")
    assert resp.intent == "out_of_scope" and steps(resp) == ["tools/list"] and resp.confidence == "low"


async def test_follow_up_uses_conversation_context(stack, make_service):
    service = make_service()
    first = await service.chat("Show active critical alarms for Boiler Feed Pump 102", "conv-follow")
    second = await service.chat("Which operating procedure applies to this alarm?", "conv-follow")
    assert first.alarm_panel.focus_alarm["asset_id"] == "BFP-102"
    assert second.entities["asset_ids"] == ["BFP-102"] and "BFP-SUCT-P-LL" in second.entities["alarm_codes"]
    assert any(c.doc_id == "SOP-BFP-001" for c in second.citations)
    other = await service.chat("Which operating procedure applies to this alarm?", "conv-other")
    assert other.entities["asset_ids"] == []  # memory is per conversation


async def test_llm_answer_is_validated_and_guarded(stack, make_service):
    llm = ScriptedLLM(
        {
            "synthesis": {
                "summary": "BFP-102 has a critical low suction pressure alarm [T4] [S99].",
                "likely_causes": [{"cause": "Deaerator level excursion", "evidence": ["T8", "S42"]}],
                "recommended_actions": [
                    {"action": "Check DA-101 level and pressure immediately", "urgency": "immediate", "citations": ["S1"]},
                    {
                        "action": "Bypass the low suction pressure trip interlock to keep the pump running",
                        "urgency": "immediate",
                        "citations": ["S1"],
                    },
                ],
                "procedures": [{"doc_id": "S1", "section": "x", "reason": "alarm response", "citation": "S1"}],
                "consistency_notes": "",
                "confidence": "high",
            }
        }
    )
    resp = await make_service(llm=llm).chat("Show active critical alarms for Boiler Feed Pump 102")
    assert resp.llm["used"] is True and llm.calls[-1]["purpose"] == "synthesis"
    assert "[S99]" not in resp.answer_markdown and "S42" not in resp.likely_causes[0].evidence
    assert [a.action for a in resp.recommended_actions] == ["Check DA-101 level and pressure immediately"]
    assert resp.procedures[0].doc_id != "S1"  # citation id mapped to the real document
    assert any("unsafe" in w.lower() for w in resp.warnings)
    prompt = llm.calls[-1]["user"]
    assert "TOOL FACTS" in prompt and '<document id="S1"' in prompt and "IGNORE ALL PREVIOUS" not in prompt


async def test_llm_failure_falls_back_to_deterministic_answer(stack, make_service):
    from copilot.llm import LLMError

    resp = await make_service(llm=ScriptedLLM({"synthesis": LLMError("timeout")})).chat("Show active alarms for K-202")
    assert resp.llm["used"] is False and resp.degraded
    assert any("deterministic composer" in w for w in resp.warnings) and "### Summary" in resp.answer_markdown
