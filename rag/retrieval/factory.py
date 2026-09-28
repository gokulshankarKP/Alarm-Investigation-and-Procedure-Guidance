from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag.config import _ENV_FILE, RagSettings
from rag.ingestion.embedder import create_embedder
from rag.retrieval.retriever import InMemoryRetriever, PgVectorRetriever, Retriever


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=_ENV_FILE, extra="ignore")

    # "pgvector" (default) or "memory" (no database; corpus is chunked and embedded at start-up).
    backend: Literal["pgvector", "memory"] = "pgvector"
    # Calibrated for nomic-embed-text: off-topic queries score <= 0.53, on-topic >= 0.67.
    min_similarity: float = Field(default=0.62, ge=0, le=1)
    top_k: int = Field(default=6, ge=1, le=20)


def create_retriever(settings: RagSettings | None = None, retrieval: RetrievalSettings | None = None) -> Retriever:
    settings = settings or RagSettings()
    retrieval = retrieval or RetrievalSettings()
    embedder = create_embedder(settings.embedding)
    if retrieval.backend == "memory":
        return InMemoryRetriever(
            settings.ingestion.document_path,
            embedder,
            min_similarity=retrieval.min_similarity,
            max_chars=settings.ingestion.chunk_max_chars,
            overlap_chars=settings.ingestion.chunk_overlap_chars,
        )
    return PgVectorRetriever(settings.database.connection_kwargs(), embedder, min_similarity=retrieval.min_similarity)
