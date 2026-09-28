"""Document ingestion: load -> chunk -> embed -> store in PostgreSQL/pgvector.

Run with ``python -m rag.ingestion`` (see ``--help``).
"""

from rag.ingestion.pipeline import IngestionReport, run_ingestion

__all__ = ["IngestionReport", "run_ingestion"]
