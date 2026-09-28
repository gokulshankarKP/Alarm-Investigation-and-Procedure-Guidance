import pytest

from copilot.intent import classify_rules, detect_intent, extract_entities
from copilot.llm import LLMError, NullLLM

SAMPLES = [
    ("Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.", "active_alarm_triage"),
    ("Why are compressor discharge pressure alarms repeatedly occurring?", "recurring_alarm_analysis"),
    ("Which alarm has the highest priority in EastRefinery, and why?", "priority_ranking"),
    ("What related assets should be inspected for this motor trip alarm?", "related_assets"),
    ("Which operating procedure applies to this alarm?", "procedure_lookup"),
    ("Are the API recommendations consistent with the maintenance manual?", "recommendation_consistency"),
    ("Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days", "recurring_alarm_analysis"),
    ("Show the alarm flood analysis for Unit 2", "kpi_analysis"),
    ("What is the capital of France?", "out_of_scope"),
    ("What does the shelving policy allow?", "document_question"),
]


@pytest.mark.parametrize(("question", "intent"), SAMPLES)
def test_rule_classifier_on_assignment_questions(question, intent):
    assert classify_rules(question, extract_entities(question))[0] == intent


def test_entity_extraction():
    e = extract_entities(
        "Investigate recurring high-severity alarms for Boiler Feed Pump 101 and K-201 "
        "(CMP-DISCH-P-H) at EastRefinery Unit 2 over the last 3 months"
    )
    assert e.asset_names == ["Boiler Feed Pump 101"] and e.asset_ids == ["K-201"]
    assert e.alarm_codes == ["CMP-DISCH-P-H"] and e.sites == ["EastRefinery"] and e.units == ["Unit 2"]
    assert set(e.severities) == {"high", "critical"} and e.lookback_days == 90 and e.status == "historical"
    assert "boiler_feed_pump" in e.asset_classes


class _LLM:
    provider, model, enabled = "fake", "fake", True

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def generate_json(self, system, user, *, purpose):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


async def test_llm_intent_is_validated_and_merged_with_rules():
    llm = _LLM(
        {
            "intent": "alarm_investigation",
            "asset_ids": ["bfp-101", "DROP TABLE x"],
            "sites": ["Mars"],
            "severities": ["urgent", "high"],
            "lookback_days": 9999,
        }
    )
    result = await detect_intent("Tell me about pump BFP-101 please", llm, mode="llm")
    assert result.intent == "alarm_investigation" and result.method == "llm+rules"
    assert result.entities.asset_ids == ["BFP-101"]  # normalised; injection-like value dropped
    assert result.entities.sites == [] and result.entities.severities == ["high"]
    assert result.entities.lookback_days is None  # out-of-range value ignored


async def test_invalid_llm_intent_or_failure_falls_back_to_rules():
    r1 = await detect_intent("Which alarm has the highest priority in EastRefinery?", _LLM({"intent": "hack"}), mode="llm")
    assert r1.intent == "priority_ranking" and r1.llm_error
    r2 = await detect_intent("Which alarm has the highest priority in EastRefinery?", _LLM(LLMError("down")), mode="llm")
    assert r2.intent == "priority_ranking" and r2.method == "rules" and "down" in r2.llm_error


async def test_hybrid_mode_skips_llm_when_rules_are_decisive():
    llm = _LLM({"intent": "document_question"})
    r = await detect_intent("Why are compressor discharge pressure alarms repeatedly occurring?", llm, mode="hybrid")
    assert llm.calls == 0 and r.intent == "recurring_alarm_analysis"
    await detect_intent("Tell me about BFP-101", llm, mode="hybrid")
    assert llm.calls == 1  # not decisive -> ask the LLM


async def test_llm_cannot_turn_off_topic_question_into_tool_use():
    r = await detect_intent("What is the capital of France?", _LLM({"intent": "alarm_investigation"}), mode="llm")
    assert r.intent == "out_of_scope"


async def test_follow_up_inherits_previous_context():
    ctx = {"asset_ids": ["BFP-102"], "asset_classes": ["boiler_feed_pump"], "alarm_codes": ["BFP-SUCT-P-LL"], "sites": ["NorthPlant"]}
    r = await detect_intent("Which operating procedure applies to this alarm?", NullLLM(), mode="rules", context=ctx)
    assert r.used_context and r.entities.asset_ids == ["BFP-102"] and r.entities.alarm_codes == ["BFP-SUCT-P-LL"]
    fresh = await detect_intent("Show active alarms for K-201", NullLLM(), mode="rules", context=ctx)
    assert not fresh.used_context and fresh.entities.asset_ids == ["K-201"]
