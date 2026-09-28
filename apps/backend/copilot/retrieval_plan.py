"""RAG step of the workflow: plan intent-specific queries, run them with metadata filters,
merge results, assign citation ids and quarantine suspected prompt-injection chunks.

Trust boundary: document text is *data*. Chunks flagged at ingestion as containing
instruction-like text (``suspected_injection``) are withheld from the LLM and shown to the
user as quarantined. Chunks from ``trust_level: untrusted`` documents are kept as evidence
but labelled UNTRUSTED everywhere (prompt, citations, GUI).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any

from copilot.schemas import Citation, QuarantinedSource
from rag.retrieval import RetrievalFilters, RetrievedChunk, Retriever


@dataclass
class PlannedQuery:
    purpose: str
    query: str
    filters: RetrievalFilters
    alarm_codes: tuple[str, ...] = ()
    top_k: int = 3


@dataclass
class RetrievalOutcome:
    chunks: list[RetrievedChunk] = field(default_factory=list)  # usable evidence, in citation order
    citations: list[Citation] = field(default_factory=list)
    quarantined: list[QuarantinedSource] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)
    low_confidence: bool = True
    reason: str | None = None


ASSET_CLASS_RELATIONS = {
    "boiler_feed_pump": ("boiler_feed_pump", "deaerator", "motor"),
    "compressor": ("compressor",),
    "motor": ("motor",),
    "deaerator": ("deaerator", "boiler_feed_pump"),
}


def plan_queries(
    question: str,
    intent: str,
    *,
    sites: list[str],
    asset_classes: list[str],
    alarm_codes: list[str],
    alarm_names: dict[str, str],
    recommendations: list[str],
) -> list[PlannedQuery]:
    classes: list[str] = []
    for cls in asset_classes:
        classes.extend(ASSET_CLASS_RELATIONS.get(cls, (cls,)))
    classes = list(dict.fromkeys(classes))
    base = RetrievalFilters(sites=tuple(sites) or None, asset_classes=tuple(classes) or None)
    codes = tuple(alarm_codes[:3])
    plan = [
        PlannedQuery(
            "question", question, base if intent != "document_question" else RetrievalFilters(sites=tuple(sites) or None), codes, 5
        )
    ]

    for code in codes[:2]:
        name = alarm_names.get(code, "")
        plan.append(
            PlannedQuery("alarm_response", f"{code} {name} alarm response operator actions", replace(base, doc_types=("sop",)), (code,), 2)
        )
    if intent in {"alarm_investigation", "recurring_alarm_analysis", "related_assets", "active_alarm_triage"} and (codes or classes):
        subject = " ".join(f"{c} {alarm_names.get(c, '')}" for c in codes) or " ".join(classes)
        plan.append(
            PlannedQuery(
                "troubleshooting",
                f"likely causes and diagnostic checks for recurring {subject}",
                replace(base, doc_types=("troubleshooting", "maintenance_manual")),
                codes,
                3,
            )
        )
    if intent == "related_assets":
        plan.append(
            PlannedQuery(
                "related_assets",
                f"related assets to inspect after {' '.join(codes) or 'trip'}",
                replace(base, doc_types=("maintenance_manual", "sop")),
                codes,
                3,
            )
        )
    if recommendations and intent in {
        "recommendation_consistency",
        "alarm_investigation",
        "active_alarm_triage",
        "priority_ranking",
        "recurring_alarm_analysis",
        "related_assets",
    }:
        plan.append(
            PlannedQuery(
                "verify_recommendations",
                " ; ".join(recommendations[:4]),
                replace(base, doc_types=("maintenance_manual", "sop", "safety", "troubleshooting")),
                codes,
                4,
            )
        )
    if intent in {"priority_ranking", "active_alarm_triage"}:
        plan.append(
            PlannedQuery(
                "priority_policy",
                "alarm priority levels response time dynamic priority scoring asset criticality",
                RetrievalFilters(doc_types=("alarm_philosophy",)),
                (),
                2,
            )
        )
    if intent == "kpi_analysis":
        plan.append(
            PlannedQuery(
                "kpi_policy",
                "alarm flood definition KPI targets chattering rationalization triggers",
                RetrievalFilters(doc_types=("alarm_philosophy",)),
                (),
                3,
            )
        )
    if intent in {"alarm_investigation", "active_alarm_triage", "related_assets", "recommendation_consistency", "priority_ranking"}:
        plan.append(
            PlannedQuery(
                "safety",
                f"safety rules trips interlocks isolation {' '.join(classes)} {' '.join(codes)}",
                replace(base, doc_types=("safety",)),
                codes,
                2,
            )
        )
    return plan


async def run_retrieval(retriever: Retriever, plan: list[PlannedQuery], *, max_chunks: int = 8) -> RetrievalOutcome:
    outcome = RetrievalOutcome()
    results = []
    for q in plan:
        res = await asyncio.to_thread(retriever.search, q.query, filters=q.filters, top_k=q.top_k, alarm_codes=q.alarm_codes)
        results.append((q, res))
        outcome.queries.append({"purpose": q.purpose, **res.to_dict()})

    # Round-robin the best chunks of each query first (diversity), then fill by score.
    selected: dict[str, RetrievedChunk] = {}
    purposes: dict[str, list[str]] = {}
    for depth in range(2):
        for q, res in results:
            if res.low_confidence and q.purpose != "question":
                continue
            if depth < len(res.chunks):
                chunk = res.chunks[depth]
                selected.setdefault(chunk.chunk_id, chunk)
                purposes.setdefault(chunk.chunk_id, []).append(q.purpose)
    rest = sorted((c for _, res in results for c in res.chunks if not res.low_confidence), key=lambda c: -c.score)
    for chunk in rest:
        if len(selected) >= max_chunks + 2:
            break
        selected.setdefault(chunk.chunk_id, chunk)

    question_result = results[0][1] if results else None
    any_confident = any(not res.low_confidence for _, res in results)
    outcome.low_confidence = not any_confident
    outcome.reason = question_result.reason if outcome.low_confidence and question_result else None
    if outcome.low_confidence:
        # Keep only chunks with an exact alarm-code match (still useful) - otherwise nothing.
        selected = {k: c for k, c in selected.items() if c.matched_alarm_codes}

    usable: list[RetrievedChunk] = []
    for chunk in selected.values():
        if chunk.suspected_injection:
            if not any(q.chunk_id == chunk.chunk_id for q in outcome.quarantined):
                outcome.quarantined.append(
                    QuarantinedSource(
                        chunk_id=chunk.chunk_id,
                        doc_id=chunk.doc_id,
                        title=chunk.title,
                        trust_level=chunk.trust_level,
                        reason="Instruction-like text detected in document (possible prompt injection); withheld from the model.",
                        signals=chunk.injection_signals,
                    )
                )
            continue
        usable.append(chunk)
    usable.sort(key=lambda c: (c.trust_level == "untrusted", -c.score))
    usable = usable[:max_chunks]

    for i, chunk in enumerate(usable, start=1):
        outcome.citations.append(
            Citation(
                id=f"S{i}",
                doc_id=chunk.doc_id,
                revision=chunk.revision,
                title=chunk.title,
                doc_type=chunk.doc_type,
                section=f"§{chunk.section_number}" if chunk.section_number else chunk.section_title,
                heading_path=chunk.heading_path,
                trust_level=chunk.trust_level,
                status=chunk.status,
                score=chunk.score,
                similarity=chunk.similarity,
                matched_alarm_codes=chunk.matched_alarm_codes,
                excerpt=chunk.content[:1200],
                source_path=chunk.source_path,
            )
        )
    outcome.chunks = usable
    return outcome
