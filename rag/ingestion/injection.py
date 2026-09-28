"""Ingestion-time heuristics for prompt-injection text embedded in documents.

Detection here only *flags* chunks (``suspected_injection`` / ``injection_signals``);
flagged chunks stay in the index so retrieval can surface them as untrusted evidence
and the copilot can warn about them. They are never treated as instructions.
"""

from __future__ import annotations

import re

_SIGNALS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+)?(the\s+)?"
        r"(previous|prior|above|earlier|system)\s+(instructions|prompts?|rules)\b",
        re.IGNORECASE,
    ),
    "role_reassignment": re.compile(r"\byou\s+are\s+now\s+(in\s+)?(a|an|the)?\s*\w+", re.IGNORECASE),
    "addressed_to_ai": re.compile(
        r"\b(note|instructions?|message)\s+(for|to)\s+(automated\s+assistants?|ai|llms?|language\s+models?|chatbots?)\b",
        re.IGNORECASE,
    ),
    "secret_exfiltration": re.compile(
        r"\b(reveal|print|show|output|disclose|expose)\b.{0,40}"
        r"\b(system\s+prompt|api\s+keys?|secrets?|passwords?|credentials|tokens?)\b",
        re.IGNORECASE,
    ),
    "citation_suppression": re.compile(r"\bdo\s+not\s+(cite|mention|reference)\s+(this|safety|the\s+source)", re.IGNORECASE),
}


def detect_injection_signals(text: str) -> tuple[str, ...]:
    """Return the names of the injection heuristics that match ``text`` (empty if none)."""
    return tuple(name for name, pattern in _SIGNALS.items() if pattern.search(text))
