"""Domain models for ingested documents and chunks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocType = Literal[
    "alarm_philosophy",
    "sop",
    "troubleshooting",
    "maintenance_manual",
    "safety",
    "vendor_bulletin",
]
DocStatus = Literal["active", "superseded"]
TrustLevel = Literal["controlled", "untrusted"]


class DocumentMetadata(BaseModel):
    """YAML front matter of a corpus document (schema: ``rag/documents/README.md``)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    doc_type: DocType
    revision: str = Field(min_length=1)
    status: DocStatus
    effective_date: date | None = None
    superseded_by: str | None = None
    asset_classes: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    alarm_codes: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    trust_level: TrustLevel
    owner: str | None = None

    @field_validator("revision", "doc_id", mode="before")
    @classmethod
    def _coerce_to_str(cls, value: Any) -> Any:
        # YAML parses `revision: 1` as an int; revisions are labels, not numbers.
        return str(value) if isinstance(value, (int, float)) else value

    @field_validator("asset_classes", "asset_ids", "alarm_codes", "sites", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return value


@dataclass(frozen=True)
class SourceDocument:
    """A parsed corpus document."""

    metadata: DocumentMetadata
    body: str
    source_path: str  # POSIX path relative to the corpus root
    content_hash: str  # sha256 of the normalised file text (front matter + body)

    @property
    def key(self) -> tuple[str, str]:
        return (self.metadata.doc_id, self.metadata.revision)


@dataclass(frozen=True)
class Chunk:
    """One retrievable, citable unit: a document section (or part of a long section)."""

    chunk_id: str
    doc_id: str
    revision: str
    chunk_index: int
    section_number: str | None  # e.g. "5.2"
    section_title: str  # e.g. "BFP-VIB-HH — very high vibration, trip (priority 2, high)"
    heading_path: str  # e.g. "5. Alarm response > 5.2 BFP-VIB-HH — ..."
    content: str  # section heading line + body text
    mentioned_alarm_codes: tuple[str, ...]
    mentioned_equipment_tags: tuple[str, ...]
    referenced_doc_ids: tuple[str, ...]
    injection_signals: tuple[str, ...]

    @property
    def suspected_injection(self) -> bool:
        return bool(self.injection_signals)
