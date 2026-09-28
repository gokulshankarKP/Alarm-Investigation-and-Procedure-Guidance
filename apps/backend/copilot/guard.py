"""Output guard: last line of defence before an answer reaches the operator.

* Removes recommended actions / answer lines that advise bypassing protections, changing
  trip setpoints, or disclosing secrets (unless the sentence is a prohibition such as
  "never bypass ...").
* Removes citation references that do not correspond to retrieved sources or successful
  tool calls (no fabricated evidence).
* Redacts credential-like strings.
"""

from __future__ import annotations

import re

from copilot.schemas import Action, Cause
from shared.observability import redact

_UNSAFE = (
    re.compile(r"\bbypass(ing|ed)?\b[^.\n]{0,50}\b(interlock|trip|protection|anti-surge|safety)", re.IGNORECASE),
    re.compile(r"\b(interlock|trip|protection|anti-surge)\b[^.\n]{0,30}\bbypass", re.IGNORECASE),
    re.compile(r"\b(raise|increase|change)\b[^.\n]{0,40}\b(trip )?setpoint\b[^.\n]{0,20}\bto\b", re.IGNORECASE),
    re.compile(r"\b(disable|jumper|force)\b[^.\n]{0,30}\b(trip|interlock|protection)", re.IGNORECASE),
    re.compile(r"\b(reveal|disclose|print)\b[^.\n]{0,40}\b(system prompt|api keys?|password|token)", re.IGNORECASE),
    re.compile(r"maintenance override mode", re.IGNORECASE),
)
_PROHIBITION = re.compile(r"\b(never|do not|don't|must not|not to|no one may|prohibited|forbid|avoid|should not|cannot)\b", re.IGNORECASE)
_REF = re.compile(r"\[((?:S|T)\d+)\]")


def is_unsafe(sentence: str) -> bool:
    return any(p.search(sentence) for p in _UNSAFE) and not _PROHIBITION.search(sentence)


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+|\n", text)


def sanitize_text(text: str, allowed_refs: set[str]) -> tuple[str, int, int]:
    """Return (clean_text, removed_unsafe_count, removed_ref_count)."""
    removed_unsafe = 0
    lines = []
    for line in text.split("\n"):
        if any(is_unsafe(s) for s in _sentences(line)):
            removed_unsafe += 1
            lines.append("> ⚠️ *A statement was removed by the safety guard (it advised bypassing protections or similar).*")
        else:
            lines.append(line)
    clean = "\n".join(lines)
    removed_refs = 0

    def _fix(match: re.Match[str]) -> str:
        nonlocal removed_refs
        if match.group(1) in allowed_refs:
            return match.group(0)
        removed_refs += 1
        return ""

    clean = _REF.sub(_fix, clean)
    return redact(clean), removed_unsafe, removed_refs


def filter_actions(actions: list[Action], allowed_refs: set[str]) -> tuple[list[Action], list[str]]:
    kept, notes = [], []
    for action in actions:
        if is_unsafe(action.action):
            notes.append(f"Removed unsafe recommended action: '{action.action[:120]}'")
            continue
        invalid = [c for c in action.citations if c not in allowed_refs]
        if invalid:
            notes.append(f"Dropped unknown citation(s) {invalid} from an action")
        kept.append(action.model_copy(update={"citations": [c for c in action.citations if c in allowed_refs]}))
    return kept, notes


def filter_causes(causes: list[Cause], allowed_refs: set[str]) -> list[Cause]:
    return [c.model_copy(update={"evidence": [e for e in c.evidence if e in allowed_refs]}) for c in causes if not is_unsafe(c.cause)]
