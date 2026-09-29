"""Ingestion pipeline: load -> chunk -> embed -> store.

Idempotent: documents whose content hash and embedding model match what is already
indexed are skipped. A failure on one document is recorded and does not stop the others.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from rag.config import RagSettings
from rag.db import create_db_engine
from rag.ingestion.chunker import build_embedding_text, chunk_document
from rag.ingestion.embedder import Embedder, create_embedder
from rag.ingestion.loader import load_corpus
from rag.ingestion.models import Chunk, SourceDocument
from rag.ingestion.store import PgVectorStore

logger = logging.getLogger(__name__)


@dataclass
class IngestionReport:
    discovered: int = 0
    ingested: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (source_path, reason)
    skipped_files: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    chunks_written: int = 0
    flagged_chunks: list[str] = field(default_factory=list)  # suspected prompt injection
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed


def _label(document: SourceDocument) -> str:
    return f"{document.metadata.doc_id} rev {document.metadata.revision}"


def run_ingestion(
    settings: RagSettings,
    *,
    rebuild: bool = False,
    prune: bool = False,
    dry_run: bool = False,
    embedder: Embedder | None = None,
) -> IngestionReport:
    started = time.perf_counter()
    report = IngestionReport()
    cfg = settings.ingestion

    loaded = load_corpus(cfg.document_path)
    report.discovered = len(loaded.documents)
    report.failed.extend(loaded.failures)
    report.skipped_files.extend(loaded.skipped)
    logger.info(
        "corpus_loaded path=%s documents=%d invalid=%d skipped=%d",
        cfg.document_path,
        len(loaded.documents),
        len(loaded.failures),
        len(loaded.skipped),
    )

    chunked: list[tuple[SourceDocument, list[Chunk]]] = []
    for document in loaded.documents:
        chunks = chunk_document(document, cfg.chunk_max_chars, cfg.chunk_overlap_chars)
        chunked.append((document, chunks))
        for chunk in chunks:
            if chunk.suspected_injection:
                report.flagged_chunks.append(chunk.chunk_id)
                logger.warning(
                    "injection_suspected chunk=%s trust_level=%s signals=%s",
                    chunk.chunk_id,
                    document.metadata.trust_level,
                    ",".join(chunk.injection_signals),
                )

    if dry_run:
        for document, chunks in chunked:
            logger.info("dry_run doc=%s chunks=%d", _label(document), len(chunks))
            report.chunks_written += len(chunks)
        report.duration_s = time.perf_counter() - started
        return report

    owns_embedder = embedder is None
    embedder = embedder or create_embedder(settings.embedding)
    logger.info(
        "db_connect target=%s embedding_model=%s dim=%d",
        settings.database.safe_description(),
        embedder.model,
        embedder.dimension,
    )
    engine = create_db_engine(settings.database.connection_kwargs())
    try:
        store = PgVectorStore(engine, embedder.dimension)
        if rebuild:
            store.drop_schema()
        store.ensure_schema()

        for document, chunks in chunked:
            label = _label(document)
            if store.is_current(document, embedder.model):
                logger.info("unchanged doc=%s", label)
                report.unchanged.append(label)
                continue
            try:
                t0 = time.perf_counter()
                texts = [build_embedding_text(document, c) for c in chunks]
                embeddings = embedder.embed_documents(texts)
                store.replace_document(document, chunks, embeddings, embedder.model)
            except Exception as exc:
                logger.error("ingest_failed doc=%s error=%s", label, exc)
                report.failed.append((document.source_path, str(exc)))
                continue
            report.ingested.append(label)
            report.chunks_written += len(chunks)
            logger.info(
                "ingested doc=%s chunks=%d duration_ms=%d",
                label,
                len(chunks),
                (time.perf_counter() - t0) * 1000,
            )

        if prune:
            # Only prune when the whole corpus loaded; otherwise a parse error would
            # delete a document that is still present on disk.
            if loaded.failures:
                logger.warning("prune_skipped reason=corpus_has_invalid_documents")
            else:
                keep = {document.key for document in loaded.documents}
                report.pruned = [f"{d} rev {r}" for d, r in store.prune(keep)]
                for label in report.pruned:
                    logger.info("pruned doc=%s", label)

        logger.info("index_stats %s", " ".join(f"{k}={v}" for k, v in store.stats().items()))
    finally:
        engine.dispose()
        if owns_embedder and hasattr(embedder, "close"):
            embedder.close()

    report.duration_s = time.perf_counter() - started
    return report
