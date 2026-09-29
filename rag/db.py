"""SQLAlchemy ORM models and engine factory for the PostgreSQL + pgvector document index.

Schema
------
``rag_documents``  one row per (doc_id, revision) with the full front-matter metadata,
                   content hash and embedding model (used to skip unchanged documents).
``rag_chunks``     one row per chunk. Document metadata is denormalised onto each chunk so
                   retrieval can filter (status, doc_type, trust_level, sites, asset_ids, ...)
                   in a single table. Includes the ``embedding`` vector (HNSW, cosine) and a
                   generated ``content_tsv`` full-text column for hybrid search.

The embedding dimension is a runtime setting, so the mapped ``embedding`` column is an
untyped ``vector``; ``schema_metadata(dim)`` returns a copy of the tables with
``vector(dim)`` for DDL.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Engine,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_EMPTY_ARRAY = text("'{}'")


def _text_array() -> Mapped[list[str]]:
    return mapped_column(ARRAY(Text), nullable=False, server_default=_EMPTY_ARRAY, default=list)


class Base(DeclarativeBase):
    pass


class RagDocument(Base):
    __tablename__ = "rag_documents"

    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    superseded_by: Mapped[str | None] = mapped_column(Text)
    trust_level: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    asset_classes: Mapped[list[str]] = _text_array()
    asset_ids: Mapped[list[str]] = _text_array()
    alarm_codes: Mapped[list[str]] = _text_array()
    sites: Mapped[list[str]] = _text_array()
    source_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list[RagChunk]] = relationship(back_populates="document", passive_deletes=True)


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text)
    revision: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_number: Mapped[str | None] = mapped_column(Text)
    section_title: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    # denormalised document metadata (retrieval filters / citation display)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    trust_level: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    asset_classes: Mapped[list[str]] = _text_array()
    asset_ids: Mapped[list[str]] = _text_array()
    alarm_codes: Mapped[list[str]] = _text_array()
    sites: Mapped[list[str]] = _text_array()
    source_path: Mapped[str] = mapped_column(Text)
    # chunk-level signals extracted from the text
    mentioned_alarm_codes: Mapped[list[str]] = _text_array()
    mentioned_equipment_tags: Mapped[list[str]] = _text_array()
    referenced_doc_ids: Mapped[list[str]] = _text_array()
    suspected_injection: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    injection_signals: Mapped[list[str]] = _text_array()
    embedding_model: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector())
    content_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', heading_path || ' ' || content)", persisted=True),
        nullable=True,
    )

    document: Mapped[RagDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        ForeignKeyConstraint(["doc_id", "revision"], ["rag_documents.doc_id", "rag_documents.revision"], ondelete="CASCADE"),
        Index(
            "rag_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("rag_chunks_content_tsv_gin", "content_tsv", postgresql_using="gin"),
        Index("rag_chunks_alarm_codes_gin", "alarm_codes", postgresql_using="gin"),
        Index("rag_chunks_mentioned_alarm_codes_gin", "mentioned_alarm_codes", postgresql_using="gin"),
        Index("rag_chunks_asset_ids_gin", "asset_ids", postgresql_using="gin"),
        Index("rag_chunks_filters_idx", "status", "doc_type", "trust_level"),
    )


def schema_metadata(dimension: int) -> MetaData:
    """Copy of the ORM tables with ``embedding`` typed as ``vector(dimension)`` (for CREATE TABLE)."""
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    metadata.tables[RagChunk.__tablename__].c.embedding.type = Vector(int(dimension))
    return metadata


def create_db_engine(connection_kwargs: dict[str, Any], **engine_kwargs: Any) -> Engine:
    """Engine over psycopg 3. Credentials go through ``connect_args`` so they never appear in the URL."""
    return create_engine("postgresql+psycopg://", connect_args=connection_kwargs, pool_pre_ping=True, **engine_kwargs)
