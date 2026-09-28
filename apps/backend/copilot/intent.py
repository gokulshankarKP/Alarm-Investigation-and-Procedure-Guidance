"""Intent detection and entity extraction.

``detect_intent`` asks the LLM for a structured intent + entities (JSON), validates every
value, and falls back to the deterministic rule-based extractor when the LLM is disabled,
fails, or returns an invalid intent. Rule-extracted entities are always merged in, so an
LLM omission (e.g. a missed asset tag) cannot drop information from the question.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from copilot.llm import LLMClient, LLMError
from shared.observability import log_event

logger = logging.getLogger(__name__)

Status = Literal["active", "historical", "any"]
Intent = Literal[
    "alarm_investigation",
    "active_alarm_triage",
    "recurring_alarm_analysis",
    "priority_ranking",
    "related_assets",
    "procedure_lookup",
    "recommendation_consistency",
    "kpi_analysis",
    "document_question",
    "out_of_scope",
]
INTENTS: dict[str, str] = {
    "alarm_investigation": "Investigate alarms on a specific asset (history, causes, actions, procedures).",
    "active_alarm_triage": "Current/active alarms on an asset or site and immediate actions.",
    "recurring_alarm_analysis": "Why an alarm or alarm type keeps recurring; patterns and root causes.",
    "priority_ranking": "Which alarm has the highest priority (in a site/unit/asset set) and why.",
    "related_assets": "Which related/connected assets to inspect for an alarm or trip.",
    "procedure_lookup": "Which operating procedure / document section applies to an alarm.",
    "recommendation_consistency": "Whether system/API recommendations agree with manuals or procedures.",
    "kpi_analysis": "Alarm KPIs: flood analysis, alarm rates, response efficiency, nuisance/chattering alarms.",
    "document_question": "General question answerable from documents only (policies, definitions, limits).",
    "out_of_scope": "Not about plant alarms, assets, procedures, or alarm management.",
}

SITES = {
    "northplant": "NorthPlant",
    "north plant": "NorthPlant",
    "southplant": "SouthPlant",
    "south plant": "SouthPlant",
    "eastrefinery": "EastRefinery",
    "east refinery": "EastRefinery",
}
CLASS_WORDS = [
    ("boiler feed pump", "boiler_feed_pump"),
    ("bfp", "boiler_feed_pump"),
    ("feed pump", "boiler_feed_pump"),
    ("compressor", "compressor"),
    ("motor", "motor"),
    ("deaerator", "deaerator"),
    ("intercooler", "heat_exchanger"),
    ("transformer", "transformer"),
    ("heater", "fired_heater"),
    ("cooling tower fan", "fan"),
    ("valve", "valve"),
    ("boiler", "boiler"),
    ("pump", "pump"),
]
_ASSET_TAG = re.compile(r"\b(BFP|DA|M|K|E|UV|PCV|FCV|BLR|CWP|CTF|H|P|TR)-\d{3}\b", re.IGNORECASE)
_NAMED_ASSET = re.compile(
    r"\b(boiler feed pump|process gas compressor|compressor|motor|deaerator|intercooler|transformer|"
    r"heater feed pump|cooling water pump|cooling tower fan|process pump|pump|heater)\s+([A-Z]{1,3}-)?(\d{3})\b",
    re.IGNORECASE,
)
_ALARM_CODE = re.compile(r"\b(?:BFP|DA|CMP|MTR|BLR|PCV|FCV|TR|CWP|CTF|HTR|P)(?:-[A-Z]+)+\b")
_ASSET_TAG_FULL = re.compile(r"(BFP|DA|M|K|E|UV|PCV|FCV|BLR|CWP|CTF|H|P|TR)-\d{3}", re.IGNORECASE)
_ALARM_CODE_FULL = re.compile(r"(?:BFP|DA|CMP|MTR|BLR|PCV|FCV|TR|CWP|CTF|HTR|P)(?:-[A-Z]+)+")
_UNIT = re.compile(r"\bunit\s*(\d{1,2})\b", re.IGNORECASE)
_LOOKBACK = re.compile(r"\b(?:last|past|previous)\s+(\d{1,3})\s*(day|week|month)s?\b", re.IGNORECASE)
_DOMAIN = re.compile(
    r"alarm|trip|asset|pump|compressor|motor|deaerator|procedure|sop|manual|maintenance|safety|priority|"
    r"flood|kpi|vibration|pressure|temperature|bearing|seal|interlock|shelv|operator|plant|refinery|"
    r"loto|lockout|isolation|setpoint|surge|recommend|troubleshoot|inspect|unit\s*\d|chatter|nuisance",
    re.IGNORECASE,
)
_CONTEXT_REF = re.compile(r"\b(this|that|these|those|it|same|the alarm|the pump|the asset)\b", re.IGNORECASE)


class Entities(BaseModel):
    asset_names: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    alarm_codes: list[str] = Field(default_factory=list)
    sites: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    severities: list[str] = Field(default_factory=list)
    status: Literal["active", "historical", "any"] = "any"
    lookback_days: int | None = None
    kpi: str | None = None

    def has_scope(self) -> bool:
        return bool(self.asset_names or self.asset_ids or self.sites or self.units or self.alarm_codes or self.asset_classes)


class IntentResult(BaseModel):
    intent: Intent
    entities: Entities
    method: str
    rationale: str = ""
    used_context: bool = False
    llm_error: str | None = None


def _dedupe(values) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def extract_entities(question: str) -> Entities:
    text = question.strip()
    lower = text.lower()
    ids = _dedupe(m.group(0).upper() for m in _ASSET_TAG.finditer(text))
    names = []
    for m in _NAMED_ASSET.finditer(text):
        kind, prefix, number = m.group(1), m.group(2) or "", m.group(3)
        names.append(f"{kind.title()} {prefix.upper()}{number}")
    classes = []
    for word, cls in CLASS_WORDS:
        if re.search(rf"\b{word}s?\b", lower):
            classes.append(cls)
            if cls == "boiler_feed_pump":
                break  # "boiler feed pump" should not also count as "pump"/"boiler"
    severities = [s for s in ("critical", "high", "medium", "low") if re.search(rf"\b{s}\b", lower)]
    if "high-severity" in lower or "high severity" in lower:
        severities = _dedupe(severities + ["high", "critical"])
    status: Literal["active", "historical", "any"] = "any"
    if re.search(r"\b(active|current|currently|right now|ongoing|standing)\b", lower):
        status = "active"
    elif re.search(r"\b(historical|history|recurring|repeated(ly)?|over the last|past|last \d+)\b", lower):
        status = "historical"
    lookback = None
    if lb := _LOOKBACK.search(text):
        lookback = int(lb.group(1)) * {"day": 1, "week": 7, "month": 30}[lb.group(2).lower()]
    kpi = None
    for word, name in (
        ("flood", "alarm_flood_index"),
        ("nuisance", "nuisance_alarm_score"),
        ("chatter", "nuisance_alarm_score"),
        ("response efficiency", "operator_response_efficiency"),
        ("acknowledg", "operator_response_efficiency"),
        ("critical density", "critical_alarm_density"),
        ("alarm rate", "average_alarm_rate"),
    ):
        if word in lower:
            kpi = name
            break
    return Entities(
        asset_names=_dedupe(names),
        asset_ids=ids,
        asset_classes=_dedupe(classes),
        alarm_codes=_dedupe(_ALARM_CODE.findall(text)),
        sites=_dedupe(v for k, v in SITES.items() if k in lower),
        units=_dedupe(f"Unit {m.group(1)}" for m in _UNIT.finditer(text)),
        severities=severities,
        status=status,
        lookback_days=lookback,
        kpi=kpi,
    )


def classify_rules(question: str, entities: Entities) -> tuple[str, str]:
    q = question.lower()
    if not _DOMAIN.search(q) and not entities.has_scope():
        return "out_of_scope", "no alarm-management vocabulary or plant entities found"
    rules = [
        (r"consisten|agree with|contradict|in line with|aligned with|match the (manual|procedure)", "recommendation_consistency"),
        (r"highest priority|most urgent|most important alarm|prioriti[sz]e|top priority|rank", "priority_ranking"),
        (
            r"related assets?|which assets?.*(inspect|check)|what .*(inspect|check).*(assets?|equipment)|connected (assets|equipment)",
            "related_assets",
        ),
        (r"which (operating )?procedure|what procedure|procedure (applies|should)|which sop|which document|what sop", "procedure_lookup"),
        (r"flood|kpi|alarm rate|nuisance|chatter|response efficiency|acknowledg\w* (time|delay)", "kpi_analysis"),
        (
            r"\bwhy\b.*(repeat|recurr|keep|again|frequent)|recurring|repeatedly|keeps? (happening|occurring|alarming)",
            "recurring_alarm_analysis",
        ),
        (r"\bactive\b|current(ly)?|right now|immediate actions?", "active_alarm_triage"),
        (r"investigat|root cause|contributing factor|analy[sz]e|what happened", "alarm_investigation"),
    ]
    for pattern, intent in rules:
        if re.search(pattern, q):
            return intent, f"matched rule /{pattern[:40]}/"
    if entities.asset_ids or entities.asset_names:
        return "alarm_investigation", "asset mentioned without a more specific request"
    return "document_question", "domain question without a specific asset"


_SYSTEM = """You classify questions for an industrial alarm-investigation copilot.
Return ONLY a JSON object with these keys:
  "intent": one of {intents}
  "asset_names": list of asset names as written (e.g. "Boiler Feed Pump 102"),
  "asset_ids": list of asset tags (e.g. "BFP-101", "K-201", "M-501"),
  "asset_classes": list from [boiler_feed_pump, compressor, motor, deaerator, heat_exchanger, valve, pump, transformer, fired_heater, fan, boiler],
  "alarm_codes": list of alarm codes (e.g. "BFP-VIB-HH", "CMP-DISCH-P-H"),
  "sites": list from [NorthPlant, SouthPlant, EastRefinery],
  "units": list like "Unit 2",
  "severities": list from [critical, high, medium, low],
  "status": "active" | "historical" | "any",
  "lookback_days": integer or null,
  "rationale": short reason for the intent.
Intent definitions:
{definitions}
Use only information present in the question or the conversation context. Do not invent assets."""


async def detect_intent(
    question: str,
    llm: LLMClient,
    *,
    mode: str = "hybrid",
    context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
) -> IntentResult:
    """``mode``: "llm" always asks the LLM; "hybrid" only when the rules are not decisive (no specific
    rule matched, or a follow-up that needs conversation context); "rules" never asks the LLM."""
    rules_entities = extract_entities(question)
    rules_intent, rules_reason = classify_rules(question, rules_entities)
    result = IntentResult(intent=cast(Intent, rules_intent), entities=rules_entities, method="rules", rationale=rules_reason)
    decisive = rules_reason.startswith("matched rule") or rules_intent == "out_of_scope"
    use_llm = mode == "llm" or (mode == "hybrid" and (not decisive or bool(context and _CONTEXT_REF.search(question))))

    if use_llm and llm.enabled:
        ctx_line = ""
        if context:
            ctx_line = f"\nConversation context (previous turn): {context}"
        if history:
            ctx_line += "\nRecent turns: " + " | ".join(f"{h['role']}: {h['content'][:160]}" for h in history[-4:])
        system = _SYSTEM.format(intents=list(INTENTS), definitions="\n".join(f"- {k}: {v}" for k, v in INTENTS.items()))
        try:
            raw = await llm.generate_json(system, f"Question: {question}{ctx_line}", purpose="intent")
            llm_intent = raw.get("intent")
            if llm_intent in INTENTS:
                merged = _merge(rules_entities, raw)
                result = IntentResult(
                    intent=cast(Intent, llm_intent), entities=merged, method="llm+rules", rationale=str(raw.get("rationale") or "")[:300]
                )
            else:
                result.llm_error = f"LLM returned invalid intent {llm_intent!r}; used rules"
        except LLMError as exc:
            result.llm_error = str(exc)[:300]

    # A clearly off-topic question stays off-topic even if the LLM guessed otherwise.
    if rules_intent == "out_of_scope" and result.intent != "out_of_scope" and not result.entities.has_scope():
        result.intent, result.method = "out_of_scope", result.method + "+guard"

    result = _apply_context(question, result, context)
    log_event(
        logger,
        "intent_detected",
        intent=result.intent,
        method=result.method,
        used_context=result.used_context,
        entities=result.entities.model_dump(exclude_defaults=True),
        llm_error=result.llm_error,
    )
    return result


def _clean_list(values: Any, pattern: re.Pattern[str] | None = None, allowed: set[str] | None = None, upper=False) -> list[str]:
    if not isinstance(values, list):
        return []
    out = []
    for v in values[:10]:
        if not isinstance(v, str) or not v.strip() or len(v) > 80:
            continue
        v = v.strip().upper() if upper else v.strip()
        if pattern and not pattern.fullmatch(v):
            continue
        if allowed is not None and v not in allowed:
            continue
        out.append(v)
    return out


def _merge(rules: Entities, raw: dict[str, Any]) -> Entities:
    classes = {c for _, c in CLASS_WORDS}
    lookback = raw.get("lookback_days")
    status = cast(Status, raw.get("status")) if raw.get("status") in ("active", "historical", "any") else rules.status
    return Entities(
        asset_names=_dedupe(rules.asset_names + _clean_list(raw.get("asset_names"))),
        asset_ids=_dedupe(rules.asset_ids + _clean_list(raw.get("asset_ids"), _ASSET_TAG_FULL, upper=True)),
        asset_classes=_dedupe(rules.asset_classes + _clean_list(raw.get("asset_classes"), allowed=classes)),
        alarm_codes=_dedupe(rules.alarm_codes + _clean_list(raw.get("alarm_codes"), _ALARM_CODE_FULL, upper=True)),
        sites=_dedupe(rules.sites + _clean_list(raw.get("sites"), allowed=set(SITES.values()))),
        units=_dedupe(rules.units + _clean_list(raw.get("units"), re.compile(r"Unit \d{1,2}"))),
        severities=_dedupe(rules.severities + _clean_list(raw.get("severities"), allowed={"critical", "high", "medium", "low"})),
        status=status if rules.status == "any" else rules.status,
        lookback_days=rules.lookback_days or (int(lookback) if isinstance(lookback, int) and 0 < lookback <= 365 else None),
        kpi=rules.kpi,
    )


def _apply_context(question: str, result: IntentResult, context: dict[str, Any] | None) -> IntentResult:
    """Inherit the previous turn's asset/alarm scope for follow-ups like 'this alarm'."""
    if not context or result.intent == "out_of_scope":
        return result
    e = result.entities
    has_asset = e.asset_ids or e.asset_names or e.sites or e.units
    refers_back = bool(_CONTEXT_REF.search(question))
    if has_asset or not (refers_back or not e.has_scope()):
        return result
    e.asset_ids = _dedupe(e.asset_ids + list(context.get("asset_ids", [])))
    e.asset_classes = _dedupe(e.asset_classes + list(context.get("asset_classes", [])))
    e.alarm_codes = _dedupe(e.alarm_codes + list(context.get("alarm_codes", [])))
    e.sites = _dedupe(e.sites + list(context.get("sites", [])))
    result.used_context = True
    if result.intent == "document_question" and (e.asset_ids or e.alarm_codes):
        result.intent = "procedure_lookup" if "procedure" in question.lower() else "alarm_investigation"
    return result
