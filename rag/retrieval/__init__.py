"""Retrieval service: hybrid (vector + keyword + exact-match) search with metadata filters."""

from rag.retrieval.factory import create_retriever
from rag.retrieval.models import RetrievalFilters, RetrievalResult, RetrievedChunk
from rag.retrieval.retriever import InMemoryRetriever, PgVectorRetriever, Retriever

__all__ = [
    "InMemoryRetriever",
    "PgVectorRetriever",
    "RetrievalFilters",
    "RetrievalResult",
    "RetrievedChunk",
    "Retriever",
    "create_retriever",
]
