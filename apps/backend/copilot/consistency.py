"""Compare system (API) recommendations with controlled document guidance.

Deterministic, explainable rules run before generation so that a conflict between the
recommendation engine and a manual is detected even if the LLM misses it. Only
``trust_level: controlled`` documents can confirm or contradict a recommendation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from copilot.schemas import Citation, ConsistencyFinding

_NEGATED = re.compile(r"\b(do not|don't|never|must not|avoid)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ConflictRule:
    name: str
    recommendation: re.Pattern[str]
    document: re.Pattern[str]
    explanation: str


RULES: tuple[ConflictRule, ...] = (
    ConflictRule(
        "restart_after_trip",
        re.compile(r"\b(restart|re-start|reset)\b", re.IGNORECASE),
        re.compile(
            r"(do not|must not|never)\b[^.\n]{0,80}\b(restart|reset)|not consistent with this manual|"
            r"must not be restarted|until the (trip )?cause (is|has been) identified|released it",
            re.IGNORECASE,
        ),
        "Controlled documents require the trip cause to be identified (and, for vibration trips, a reliability "
        "engineer review) before any reset or restart.",
    ),
    ConflictRule(
        "spare_into_restriction",
        re.compile(r"\bstart\b[^.]{0,30}\bspare\b", re.IGNORECASE),
        re.compile(r"do not start the spare|only after the downstream restriction|start the spare compressor k-203 only", re.IGNORECASE),
        "Documents say not to start the spare compressor until the downstream restriction is identified and "
        "cleared, otherwise it trips for the same reason. (This advice only exists in the superseded revision A.)",
    ),
    ConflictRule(
        "bypass_or_setpoint_change",
        re.compile(r"\b(bypass|jumper|disable|force)\b|\b(raise|increase)\b[^.]{0,30}\bsetpoint", re.IGNORECASE),
        re.compile(
            r"never\b[^.]{0,40}bypass|must \*?\*?never\*?\*? be bypassed|do not raise the hh trip setpoint|"
            r"management of change|do not bypass",
            re.IGNORECASE,
        ),
        "Trips and interlocks must never be bypassed and trip setpoints change only through Management of Change.",
    ),
)

_GENERIC = {
    "check",
    "alarm",
    "alarms",
    "pump",
    "the",
    "and",
    "with",
    "from",
    "this",
    "that",
    "confirm",
    "immediately",
    "ensure",
    "operator",
    "system",
    "restore",
    "after",
    "before",
    "within",
    "minutes",
}
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 4 and w not in _GENERIC}


def evaluate(recommendations: list[dict], citations: list[Citation], tool_ref: str | None) -> list[ConsistencyFinding]:
    controlled = [c for c in citations if c.trust_level == "controlled" and c.status == "active"]
    findings: list[ConsistencyFinding] = []
    for rec in recommendations:
        action = str(rec.get("action", "")).strip()
        if not action:
            continue
        finding = None
        if not _NEGATED.search(action):
            for rule in RULES:
                if not rule.recommendation.search(action):
                    continue
                hits = [c.id for c in controlled if rule.document.search(c.excerpt)]
                if hits:
                    finding = ConsistencyFinding(
                        api_recommendation=action,
                        verdict="inconsistent",
                        explanation=rule.explanation,
                        citations=hits[:3],
                        tool_ref=tool_ref,
                    )
                    break
        if finding is None:
            rec_terms = _terms(action)
            best, overlap = None, 0
            for c in controlled:
                n = len(rec_terms & _terms(c.excerpt))
                if n > overlap:
                    best, overlap = c, n
            if best is not None and overlap >= 3:
                finding = ConsistencyFinding(
                    api_recommendation=action,
                    verdict="consistent",
                    explanation=f"Matches guidance in {best.doc_id} {best.section}.",
                    citations=[best.id],
                    tool_ref=tool_ref,
                )
            else:
                finding = ConsistencyFinding(
                    api_recommendation=action,
                    verdict="not_covered",
                    explanation="No retrieved controlled document confirms or contradicts this action.",
                    tool_ref=tool_ref,
                )
        findings.append(finding)
    return findings
