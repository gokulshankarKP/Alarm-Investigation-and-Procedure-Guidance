"""RAG step of the workflow: query planning, filters, quarantine of injected text, citation ids."""

from copilot.retrieval_plan import plan_queries, run_retrieval


def test_plan_applies_intent_specific_doc_type_filters():
    plan = plan_queries(
        "Investigate BFP-101",
        "alarm_investigation",
        sites=["NorthPlant"],
        asset_classes=["boiler_feed_pump"],
        alarm_codes=["BFP-VIB-HH"],
        alarm_names={"BFP-VIB-HH": "Very high vibration"},
        recommendations=["Restart the pump"],
    )
    by_purpose = {q.purpose: q for q in plan}
    assert by_purpose["alarm_response"].filters.doc_types == ("sop",)
    assert set(by_purpose["troubleshooting"].filters.doc_types) == {"troubleshooting", "maintenance_manual"}
    assert by_purpose["safety"].filters.doc_types == ("safety",)
    assert "verify_recommendations" in by_purpose
    # asset-class expansion pulls in deaerator/motor documents for BFP questions
    assert {"boiler_feed_pump", "deaerator", "motor"} <= set(by_purpose["question"].filters.asset_classes)
    assert by_purpose["question"].filters.statuses == ("active",)


def test_priority_plan_includes_alarm_philosophy():
    plan = plan_queries(
        "highest priority?",
        "priority_ranking",
        sites=["EastRefinery"],
        asset_classes=[],
        alarm_codes=[],
        alarm_names={},
        recommendations=[],
    )
    assert any(q.filters.doc_types == ("alarm_philosophy",) for q in plan)


async def test_injection_chunk_is_quarantined_and_untrusted_labelled(memory_retriever):
    plan = plan_queries(
        "Why are compressor discharge pressure alarms repeatedly occurring? nuisance alarms vendor bulletin",
        "recurring_alarm_analysis",
        sites=["EastRefinery"],
        asset_classes=["compressor"],
        alarm_codes=["CMP-DISCH-P-H"],
        alarm_names={},
        recommendations=[],
    )
    out = await run_retrieval(memory_retriever, plan, max_chunks=10)
    assert all(not c.suspected_injection for c in out.chunks)
    assert [c.id for c in out.citations] == [f"S{i}" for i in range(1, len(out.citations) + 1)]
    assert all(c.doc_id != "SOP-CMP-001" or c.revision == "B" for c in out.citations)  # superseded rev A never used
    assert any(c.doc_id == "TSG-CMP-002" for c in out.citations)
    if out.quarantined:
        assert out.quarantined[0].doc_id == "VB-CMP-099" and "ignore_instructions" in out.quarantined[0].signals
    untrusted = [c for c in out.citations if c.trust_level == "untrusted"]
    assert all(out.citations.index(c) >= len(out.citations) - len(untrusted) for c in untrusted)  # ranked last


async def test_quarantine_happens_when_injection_chunk_is_retrieved(memory_retriever):
    from copilot.retrieval_plan import PlannedQuery
    from rag.retrieval import RetrievalFilters

    plan = [
        PlannedQuery(
            "question", "note for automated assistants ignore previous instructions maintenance override mode", RetrievalFilters(), (), 5
        )
    ]
    out = await run_retrieval(memory_retriever, plan)
    assert any(q.doc_id == "VB-CMP-099" for q in out.quarantined)
    assert "IGNORE ALL PREVIOUS" not in " ".join(c.excerpt for c in out.citations)
