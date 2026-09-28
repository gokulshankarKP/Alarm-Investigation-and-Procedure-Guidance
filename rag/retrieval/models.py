"""Retrieval contracts shared by all retriever backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class RetrievalFilters:
    """Metadata filters applied before ranking.

    ``statuses`` defaults to active documents only, so superseded revisions are never
    retrieved unless explicitly requested. Safety documents (``asset_classes: [all]``) and
    documents without a site list always pass the site/asset-class filters.
    """

    statuses: tuple[str, ...] = ("active",)
    doc_types: tuple[str, ...] | None = None
    sites: tuple[str, ...] | None = None
    asset_classes: tuple[str, ...] | None = None
    exclude_untrusted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in self.__dict__.items() if v is not None}


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    revision: str
    title: str
    doc_type: str
    status: str
    trust_level: str
    section_number: str | None
    section_title: str
    heading_path: str
    content: str
    source_path: str
    effective_date: date | None
    suspected_injection: bool
    injection_signals: list[str]
    similarity: float = 0.0
    keyword_score: float = 0.0
    score: float = 0.0
    matched_alarm_codes: list[str] = field(default_factory=list)
    matched_asset_ids: list[str] = field(default_factory=list)

    @property
    def citation_label(self) -> str:
        section = f" §{self.section_number}" if self.section_number else f" – {self.section_title}"
        return f"{self.doc_id} rev {self.revision}{section}"

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["effective_date"] = self.effective_date.isoformat() if self.effective_date else None
        data["citation_label"] = self.citation_label
        return data


@dataclass
class RetrievalResult:
    query: str
    filters: RetrievalFilters
    chunks: list[RetrievedChunk]
    top_similarity: float
    low_confidence: bool
    reason: str | None = None
    alarm_codes: list[str] = field(default_factory=list)
    asset_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "filters": self.filters.as_dict(),
            "top_similarity": round(self.top_similarity, 4),
            "low_confidence": self.low_confidence,
            "reason": self.reason,
            "alarm_codes": self.alarm_codes,
            "asset_ids": self.asset_ids,
            "chunks": [c.chunk_id for c in self.chunks],
        }
