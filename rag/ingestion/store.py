"""PostgreSQL + pgvector storage for documents and chunks, via the SQLAlchemy ORM.

The schema (tables, HNSW / GIN indexes, generated ``content_tsv`` column) is defined by the
models in ``rag.db``. All statements are built by SQLAlchemy with bound parameters.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
from sqlalchemy import Engine, delete, func, select, text, tuple_
from sqlalchemy.orm import sessionmaker

from rag.db import RagChunk, RagDocument, schema_metadata
from rag.ingestion.models import Chunk, SourceDocument

logger = logging.getLogger(__name__)


class SchemaMismatchError(RuntimeError):
    """The existing tables were created for a different embedding dimension."""


class PgVectorStore:
    def __init__(self, engine: Engine, dimension: int) -> None:
        self._engine = engine
        self._dimension = dimension
        self._session = sessionmaker(engine, expire_on_commit=False)

    # -- schema ---------------------------------------------------------------------------

    def ensure_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            existing = conn.execute(
                text("SELECT a.atttypmod FROM pg_attribute a WHERE a.attrelid = to_regclass('rag_chunks') AND a.attname = 'embedding'")
            ).scalar()
            if existing is not None and existing != self._dimension:
                raise SchemaMismatchError(
                    f"rag_chunks.embedding is vector({existing}) but EMBEDDING_DIMENSION="
                    f"{self._dimension}; re-run with --rebuild to recreate the index"
                )
            schema_metadata(self._dimension).create_all(conn, checkfirst=True)

    def drop_schema(self) -> None:
        with self._engine.begin() as conn:
            schema_metadata(self._dimension).drop_all(conn, checkfirst=True)
        logger.info("schema_dropped tables=rag_chunks,rag_documents")

    # -- documents ------------------------------------------------------------------------

    def is_current(self, document: SourceDocument, embedding_model: str) -> bool:
        """True when this exact document content is already indexed with this model."""
        with self._session() as session:
            row = session.get(RagDocument, document.key)
            return row is not None and row.content_hash == document.content_hash and row.embedding_model == embedding_model

    def replace_document(
        self,
        document: SourceDocument,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
    ) -> None:
        """Atomically upsert the document row and replace all of its chunks."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")

        meta = document.metadata
        with self._session.begin() as session:
            session.merge(
                RagDocument(
                    **_metadata_fields(document),
                    superseded_by=meta.superseded_by,
                    owner=meta.owner,
                    content_hash=document.content_hash,
                    embedding_model=embedding_model,
                    chunk_count=len(chunks),
                    ingested_at=func.now(),
                )
            )
            session.execute(delete(RagChunk).where(RagChunk.doc_id == meta.doc_id, RagChunk.revision == meta.revision))
            session.add_all(
                RagChunk(
                    **_metadata_fields(document),
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    section_number=chunk.section_number,
                    section_title=chunk.section_title,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    char_count=len(chunk.content),
                    mentioned_alarm_codes=list(chunk.mentioned_alarm_codes),
                    mentioned_equipment_tags=list(chunk.mentioned_equipment_tags),
                    referenced_doc_ids=list(chunk.referenced_doc_ids),
                    suspected_injection=chunk.suspected_injection,
                    injection_signals=list(chunk.injection_signals),
                    embedding_model=embedding_model,
                    embedding=_to_vector(embedding),
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            )

    def prune(self, keep: set[tuple[str, str]]) -> list[tuple[str, str]]:
        """Delete indexed documents (and their chunks) that are no longer in the corpus."""
        with self._session.begin() as session:
            indexed = session.execute(select(RagDocument.doc_id, RagDocument.revision)).tuples().all()
            stale = [key for key in indexed if key not in keep]
            if stale:
                # rag_chunks rows go with them via ON DELETE CASCADE.
                session.execute(delete(RagDocument).where(tuple_(RagDocument.doc_id, RagDocument.revision).in_(stale)))
        return stale

    def stats(self) -> dict[str, int]:
        with self._session() as session:
            documents = session.scalar(select(func.count()).select_from(RagDocument)) or 0
            chunks = session.scalar(select(func.count()).select_from(RagChunk)) or 0
        return {"documents": documents, "chunks": chunks}


def _metadata_fields(document: SourceDocument) -> dict[str, object]:
    meta = document.metadata
    return {
        "doc_id": meta.doc_id,
        "revision": meta.revision,
        "title": meta.title,
        "doc_type": meta.doc_type,
        "status": meta.status,
        "effective_date": meta.effective_date,
        "trust_level": meta.trust_level,
        "asset_classes": list(meta.asset_classes),
        "asset_ids": list(meta.asset_ids),
        "alarm_codes": list(meta.alarm_codes),
        "sites": list(meta.sites),
        "source_path": document.source_path,
    }


def _to_vector(values: Sequence[float]) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)
