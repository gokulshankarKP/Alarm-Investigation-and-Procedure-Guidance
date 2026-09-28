"""PostgreSQL + pgvector storage for documents and chunks.

Schema
------
``rag_documents``  one row per (doc_id, revision) with the full front-matter metadata,
                   content hash and embedding model (used to skip unchanged documents).
``rag_chunks``     one row per chunk. Document metadata is denormalised onto each chunk so
                   retrieval can filter (status, doc_type, trust_level, sites, asset_ids, ...)
                   in a single table. Includes the ``embedding`` vector (HNSW, cosine) and a
                   generated ``content_tsv`` full-text column for hybrid search.

All statements use bound parameters; identifiers are fixed constants.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql

from rag.ingestion.models import Chunk, SourceDocument

logger = logging.getLogger(__name__)


class SchemaMismatchError(RuntimeError):
    """The existing tables were created for a different embedding dimension."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_documents (
    doc_id           text        NOT NULL,
    revision         text        NOT NULL,
    title            text        NOT NULL,
    doc_type         text        NOT NULL,
    status           text        NOT NULL,
    effective_date   date,
    superseded_by    text,
    trust_level      text        NOT NULL,
    owner            text,
    asset_classes    text[]      NOT NULL DEFAULT '{{}}',
    asset_ids        text[]      NOT NULL DEFAULT '{{}}',
    alarm_codes      text[]      NOT NULL DEFAULT '{{}}',
    sites            text[]      NOT NULL DEFAULT '{{}}',
    source_path      text        NOT NULL,
    content_hash     text        NOT NULL,
    embedding_model  text        NOT NULL,
    chunk_count      integer     NOT NULL,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, revision)
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id                  text        PRIMARY KEY,
    doc_id                    text        NOT NULL,
    revision                  text        NOT NULL,
    chunk_index               integer     NOT NULL,
    section_number            text,
    section_title             text        NOT NULL,
    heading_path              text        NOT NULL,
    content                   text        NOT NULL,
    char_count                integer     NOT NULL,
    -- denormalised document metadata (retrieval filters / citation display)
    title                     text        NOT NULL,
    doc_type                  text        NOT NULL,
    status                    text        NOT NULL,
    trust_level               text        NOT NULL,
    effective_date            date,
    asset_classes             text[]      NOT NULL DEFAULT '{{}}',
    asset_ids                 text[]      NOT NULL DEFAULT '{{}}',
    alarm_codes               text[]      NOT NULL DEFAULT '{{}}',
    sites                     text[]      NOT NULL DEFAULT '{{}}',
    source_path               text        NOT NULL,
    -- chunk-level signals extracted from the text
    mentioned_alarm_codes     text[]      NOT NULL DEFAULT '{{}}',
    mentioned_equipment_tags  text[]      NOT NULL DEFAULT '{{}}',
    referenced_doc_ids        text[]      NOT NULL DEFAULT '{{}}',
    suspected_injection       boolean     NOT NULL DEFAULT false,
    injection_signals         text[]      NOT NULL DEFAULT '{{}}',
    embedding_model           text        NOT NULL,
    embedding                 vector({dim}) NOT NULL,
    content_tsv               tsvector GENERATED ALWAYS AS (
        to_tsvector('english', heading_path || ' ' || content)
    ) STORED,
    FOREIGN KEY (doc_id, revision) REFERENCES rag_documents (doc_id, revision) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS rag_chunks_content_tsv_gin ON rag_chunks USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS rag_chunks_alarm_codes_gin ON rag_chunks USING gin (alarm_codes);
CREATE INDEX IF NOT EXISTS rag_chunks_mentioned_alarm_codes_gin
    ON rag_chunks USING gin (mentioned_alarm_codes);
CREATE INDEX IF NOT EXISTS rag_chunks_asset_ids_gin ON rag_chunks USING gin (asset_ids);
CREATE INDEX IF NOT EXISTS rag_chunks_filters_idx ON rag_chunks (status, doc_type, trust_level);
"""

_UPSERT_DOCUMENT = """
INSERT INTO rag_documents (
    doc_id, revision, title, doc_type, status, effective_date, superseded_by, trust_level,
    owner, asset_classes, asset_ids, alarm_codes, sites, source_path, content_hash,
    embedding_model, chunk_count, ingested_at
) VALUES (
    %(doc_id)s, %(revision)s, %(title)s, %(doc_type)s, %(status)s, %(effective_date)s,
    %(superseded_by)s, %(trust_level)s, %(owner)s, %(asset_classes)s, %(asset_ids)s,
    %(alarm_codes)s, %(sites)s, %(source_path)s, %(content_hash)s, %(embedding_model)s,
    %(chunk_count)s, now()
)
ON CONFLICT (doc_id, revision) DO UPDATE SET
    title = EXCLUDED.title, doc_type = EXCLUDED.doc_type, status = EXCLUDED.status,
    effective_date = EXCLUDED.effective_date, superseded_by = EXCLUDED.superseded_by,
    trust_level = EXCLUDED.trust_level, owner = EXCLUDED.owner,
    asset_classes = EXCLUDED.asset_classes, asset_ids = EXCLUDED.asset_ids,
    alarm_codes = EXCLUDED.alarm_codes, sites = EXCLUDED.sites,
    source_path = EXCLUDED.source_path, content_hash = EXCLUDED.content_hash,
    embedding_model = EXCLUDED.embedding_model, chunk_count = EXCLUDED.chunk_count,
    ingested_at = now()
"""

_INSERT_CHUNK = """
INSERT INTO rag_chunks (
    chunk_id, doc_id, revision, chunk_index, section_number, section_title, heading_path,
    content, char_count, title, doc_type, status, trust_level, effective_date, asset_classes,
    asset_ids, alarm_codes, sites, source_path, mentioned_alarm_codes, mentioned_equipment_tags,
    referenced_doc_ids, suspected_injection, injection_signals, embedding_model, embedding
) VALUES (
    %(chunk_id)s, %(doc_id)s, %(revision)s, %(chunk_index)s, %(section_number)s,
    %(section_title)s, %(heading_path)s, %(content)s, %(char_count)s, %(title)s, %(doc_type)s,
    %(status)s, %(trust_level)s, %(effective_date)s, %(asset_classes)s, %(asset_ids)s,
    %(alarm_codes)s, %(sites)s, %(source_path)s, %(mentioned_alarm_codes)s,
    %(mentioned_equipment_tags)s, %(referenced_doc_ids)s, %(suspected_injection)s,
    %(injection_signals)s, %(embedding_model)s, %(embedding)s
)
"""


class PgVectorStore:
    def __init__(self, conn: psycopg.Connection, dimension: int) -> None:
        self._conn = conn
        self._dimension = dimension

    # -- schema ---------------------------------------------------------------------------

    def ensure_schema(self) -> None:
        with self._conn.transaction():
            self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(self._conn)
            existing = self._existing_dimension()
            if existing is not None and existing != self._dimension:
                raise SchemaMismatchError(
                    f"rag_chunks.embedding is vector({existing}) but EMBEDDING_DIMENSION="
                    f"{self._dimension}; re-run with --rebuild to recreate the index"
                )
            self._conn.execute(sql.SQL(_SCHEMA.format(dim=int(self._dimension))))

    def drop_schema(self) -> None:
        with self._conn.transaction():
            self._conn.execute("DROP TABLE IF EXISTS rag_chunks")
            self._conn.execute("DROP TABLE IF EXISTS rag_documents")
        logger.info("schema_dropped tables=rag_chunks,rag_documents")

    def _existing_dimension(self) -> int | None:
        row = self._conn.execute(
            """
            SELECT a.atttypmod FROM pg_attribute a
            WHERE a.attrelid = to_regclass('rag_chunks') AND a.attname = 'embedding'
            """
        ).fetchone()
        return int(row[0]) if row else None

    # -- documents ------------------------------------------------------------------------

    def is_current(self, document: SourceDocument, embedding_model: str) -> bool:
        """True when this exact document content is already indexed with this model."""
        row = self._conn.execute(
            "SELECT content_hash, embedding_model FROM rag_documents WHERE doc_id = %s AND revision = %s",
            document.key,
        ).fetchone()
        return row is not None and row[0] == document.content_hash and row[1] == embedding_model

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
        doc_params = {
            **_metadata_params(document),
            "superseded_by": meta.superseded_by,
            "owner": meta.owner,
            "content_hash": document.content_hash,
            "embedding_model": embedding_model,
            "chunk_count": len(chunks),
        }
        chunk_params = [
            {
                **_metadata_params(document),
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "section_number": chunk.section_number,
                "section_title": chunk.section_title,
                "heading_path": chunk.heading_path,
                "content": chunk.content,
                "char_count": len(chunk.content),
                "mentioned_alarm_codes": list(chunk.mentioned_alarm_codes),
                "mentioned_equipment_tags": list(chunk.mentioned_equipment_tags),
                "referenced_doc_ids": list(chunk.referenced_doc_ids),
                "suspected_injection": chunk.suspected_injection,
                "injection_signals": list(chunk.injection_signals),
                "embedding_model": embedding_model,
                "embedding": _to_vector(embedding),
            }
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

        with self._conn.transaction():
            self._conn.execute(_UPSERT_DOCUMENT, doc_params)
            self._conn.execute("DELETE FROM rag_chunks WHERE doc_id = %s AND revision = %s", document.key)
            with self._conn.cursor() as cur:
                cur.executemany(_INSERT_CHUNK, chunk_params)

    def prune(self, keep: set[tuple[str, str]]) -> list[tuple[str, str]]:
        """Delete indexed documents (and their chunks) that are no longer in the corpus."""
        with self._conn.transaction():
            indexed = self._conn.execute("SELECT doc_id, revision FROM rag_documents").fetchall()
            stale = [tuple(row) for row in indexed if tuple(row) not in keep]
            for doc_id, revision in stale:
                self._conn.execute("DELETE FROM rag_documents WHERE doc_id = %s AND revision = %s", (doc_id, revision))
        return stale

    def stats(self) -> dict[str, int]:
        row = self._conn.execute("SELECT (SELECT count(*) FROM rag_documents), (SELECT count(*) FROM rag_chunks)").fetchone()
        assert row is not None
        return {"documents": row[0], "chunks": row[1]}


def _metadata_params(document: SourceDocument) -> dict[str, object]:
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
