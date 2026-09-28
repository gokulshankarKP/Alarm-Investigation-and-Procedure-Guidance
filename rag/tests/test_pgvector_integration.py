"""PostgreSQL + pgvector ingestion and retrieval (runs only when a database is reachable).

Uses a separate database (``<DB_NAME>_test``) and the hashing embedder, so it never touches
the real index or needs Ollama.
"""

from __future__ import annotations

import pytest

from rag.config import DatabaseSettings, EmbeddingSettings, IngestionSettings, RagSettings
from rag.ingestion.embedder import HashingEmbedder
from rag.ingestion.pipeline import run_ingestion
from rag.retrieval import PgVectorRetriever, RetrievalFilters

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def test_db():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    base = DatabaseSettings()
    name = f"{base.name}_test"
    try:
        with psycopg.connect(**{**base.connection_kwargs(), "dbname": "postgres", "connect_timeout": 3}, autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    return DatabaseSettings(
        DB_NAME=name, DB_HOST=base.host, DB_PORT=base.port, DB_USER=base.user, DB_PASSWORD=base.password.get_secret_value()
    )


@pytest.fixture(scope="module")
def settings(test_db):
    return RagSettings(
        database=test_db, embedding=EmbeddingSettings(EMBEDDING_PROVIDER="hash", EMBEDDING_DIMENSION=768), ingestion=IngestionSettings()
    )


def test_ingestion_is_idempotent_and_complete(settings):
    first = run_ingestion(settings, rebuild=True, embedder=HashingEmbedder(768))
    assert first.ok and len(first.ingested) == 11 and first.chunks_written == 73
    assert first.flagged_chunks == ["VB-CMP-099::rev1::002"]
    second = run_ingestion(settings, embedder=HashingEmbedder(768))
    assert second.ingested == [] and len(second.unchanged) == 11


def test_pgvector_retrieval_filters_and_boosts(settings):
    run_ingestion(settings, embedder=HashingEmbedder(768))
    r = PgVectorRetriever(settings.database.connection_kwargs(), HashingEmbedder(768), min_similarity=0.1)
    assert r.ping() == {"documents": 10, "chunks": 73}
    res = r.search("alarm response", alarm_codes=["BFP-VIB-HH"], filters=RetrievalFilters(doc_types=("sop",)), top_k=3)
    assert res.chunks[0].citation_label == "SOP-BFP-001 rev C §5.2"
    res = r.search("CMP-DISCH-P-H spare compressor", alarm_codes=["CMP-DISCH-P-H"], top_k=10)
    assert all(c.status == "active" for c in res.chunks)


def test_sql_injection_in_query_text_is_harmless(settings):
    r = PgVectorRetriever(settings.database.connection_kwargs(), HashingEmbedder(768), min_similarity=0.1)
    res = r.search("'; DROP TABLE rag_chunks; -- & | ! :*", filters=RetrievalFilters(sites=("x'); DROP TABLE y; --",)))
    assert isinstance(res.chunks, list)
    assert r.ping()["chunks"] == 73
