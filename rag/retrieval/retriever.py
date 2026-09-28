"""Hybrid retrieval: vector similarity + full-text keyword match + exact alarm-code/asset boosts.

Ranking
-------
1. Up to ``candidates`` chunks by cosine similarity and up to ``candidates`` by keyword
   score are fetched, both after metadata filtering.
2. They are fused with Reciprocal Rank Fusion (k=60).
3. Exact matches boost the score: an alarm code mentioned in the chunk text (+0.02) or
   listed in the document front matter (+0.008), and an asset id in the document (+0.006).
4. Confidence: the result is *low confidence* when the best cosine similarity is below
   ``min_similarity`` and no exact alarm-code match was found. Callers must then say the
   documentation does not cover the question instead of answering from weak evidence.

Two backends share this logic: ``PgVectorRetriever`` (PostgreSQL + pgvector, production)
and ``InMemoryRetriever`` (numpy, used by tests/CI or when no database is configured).
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Protocol

import numpy as np

from rag.ingestion.chunker import build_embedding_text, chunk_document
from rag.ingestion.embedder import Embedder
from rag.ingestion.loader import load_corpus
from rag.retrieval.models import RetrievalFilters, RetrievalResult, RetrievedChunk
from shared.observability import log_event

logger = logging.getLogger(__name__)

RRF_K = 60
BOOST_CHUNK_CODE = 0.02
BOOST_DOC_CODE = 0.008
BOOST_ASSET = 0.006
_WORD = re.compile(r"[A-Za-z0-9]+")
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "be",
    "what",
    "which",
    "why",
    "how",
    "this",
    "that",
    "with",
    "by",
    "at",
    "from",
    "it",
    "as",
    "do",
    "does",
    "should",
    "can",
    "i",
    "we",
    "me",
    "show",
    "give",
    "tell",
    "about",
    "any",
    "all",
    "our",
    "my",
    "there",
    "these",
    "those",
    "please",
}


def query_terms(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 1][:24]


class Retriever(Protocol):
    def ping(self) -> dict: ...

    def search(
        self,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        top_k: int = 6,
        alarm_codes: Sequence[str] = (),
        asset_ids: Sequence[str] = (),
    ) -> RetrievalResult: ...


class _Candidate:
    __slots__ = ("chunk", "chunk_codes", "doc_assets", "doc_codes", "keyword", "kw_rank", "similarity", "vec_rank")

    def __init__(self, chunk: RetrievedChunk, doc_codes: Sequence[str], doc_assets: Sequence[str], chunk_codes: Sequence[str]):
        self.chunk = chunk
        self.similarity = 0.0
        self.keyword = 0.0
        self.vec_rank: int | None = None
        self.kw_rank: int | None = None
        self.doc_codes = set(doc_codes)
        self.doc_assets = set(doc_assets)
        self.chunk_codes = set(chunk_codes)


def _fuse(
    query: str,
    filters: RetrievalFilters,
    candidates: dict[str, _Candidate],
    top_k: int,
    alarm_codes: Sequence[str],
    asset_ids: Sequence[str],
    min_similarity: float,
) -> RetrievalResult:
    codes, assets = set(alarm_codes), set(asset_ids)
    ranked: list[RetrievedChunk] = []
    for cand in candidates.values():
        score = 0.0
        if cand.vec_rank is not None:
            score += 1 / (RRF_K + cand.vec_rank)
        if cand.kw_rank is not None:
            score += 1 / (RRF_K + cand.kw_rank)
        chunk_hits = sorted(codes & cand.chunk_codes)
        doc_hits = sorted(codes & cand.doc_codes)
        asset_hits = sorted(assets & cand.doc_assets)
        score += BOOST_CHUNK_CODE * min(len(chunk_hits), 2) + BOOST_DOC_CODE * bool(doc_hits) + BOOST_ASSET * bool(asset_hits)
        chunk = cand.chunk
        chunk.similarity = round(cand.similarity, 4)
        chunk.keyword_score = round(cand.keyword, 4)
        chunk.score = round(score, 5)
        chunk.matched_alarm_codes = sorted(set(chunk_hits) | set(doc_hits))
        chunk.matched_asset_ids = asset_hits
        ranked.append(chunk)
    ranked.sort(key=lambda c: (-c.score, -c.similarity))
    top = ranked[:top_k]

    top_similarity = max((c.similarity for c in ranked), default=0.0)
    exact = any(c.matched_alarm_codes for c in top)
    low = not top or (top_similarity < min_similarity and not exact)
    reason = None
    if not top:
        reason = "no documents matched the filters"
    elif low:
        reason = f"best similarity {top_similarity:.2f} below threshold {min_similarity:.2f} and no exact alarm-code match"
    log_event(
        logger,
        "rag_retrieval",
        query=query[:200],
        filters=filters.as_dict(),
        results=len(top),
        top_similarity=round(top_similarity, 3),
        low_confidence=low,
        doc_ids=[c.chunk_id for c in top],
    )
    return RetrievalResult(
        query=query,
        filters=filters,
        chunks=top,
        top_similarity=top_similarity,
        low_confidence=low,
        reason=reason,
        alarm_codes=sorted(codes),
        asset_ids=sorted(assets),
    )


# -- PostgreSQL / pgvector ------------------------------------------------------------------

_FILTER_SQL = """
    status = ANY(%(statuses)s)
    AND (%(doc_types)s::text[] IS NULL OR doc_type = ANY(%(doc_types)s))
    AND (%(sites)s::text[] IS NULL OR sites && %(sites)s OR cardinality(sites) = 0)
    AND (%(asset_classes)s::text[] IS NULL OR asset_classes && %(asset_classes)s OR 'all' = ANY(asset_classes))
    AND (NOT %(exclude_untrusted)s OR trust_level <> 'untrusted')
"""

_COLUMNS = """
    chunk_id, doc_id, revision, title, doc_type, status, trust_level, section_number, section_title,
    heading_path, content, source_path, effective_date, suspected_injection, injection_signals,
    alarm_codes, asset_ids, mentioned_alarm_codes
"""


class PgVectorRetriever:
    def __init__(self, connection_kwargs: dict, embedder: Embedder, *, min_similarity: float = 0.62, candidates: int = 20) -> None:
        self._conninfo = connection_kwargs
        self._embedder = embedder
        self._min_similarity = min_similarity
        self._candidates = candidates

    def _connect(self):
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(**self._conninfo, autocommit=True)
        register_vector(conn)
        return conn

    def ping(self) -> dict:
        with self._connect() as conn:
            docs, chunks = conn.execute("SELECT count(DISTINCT doc_id), count(*) FROM rag_chunks").fetchone()
        return {"documents": docs, "chunks": chunks}

    def search(self, query, *, filters=None, top_k=6, alarm_codes=(), asset_ids=()) -> RetrievalResult:
        filters = filters or RetrievalFilters()
        vector = np.asarray(self._embedder.embed_query(query), dtype=np.float32)
        params = {
            "statuses": list(filters.statuses),
            "doc_types": list(filters.doc_types) if filters.doc_types else None,
            "sites": list(filters.sites) if filters.sites else None,
            "asset_classes": list(filters.asset_classes) if filters.asset_classes else None,
            "exclude_untrusted": filters.exclude_untrusted,
            "vec": vector,
            "limit": self._candidates,
            # Alphanumeric terms only, OR-ed: safe to_tsquery syntax. Codes match via mentioned_alarm_codes.
            "tsquery": " | ".join(dict.fromkeys(query_terms(query))),
            "codes": list(alarm_codes),
        }
        candidates: dict[str, _Candidate] = {}
        with self._connect() as conn:
            vec_rows = conn.execute(
                f"SELECT {_COLUMNS}, 1 - (embedding <=> %(vec)s) AS sim FROM rag_chunks "
                f"WHERE {_FILTER_SQL} ORDER BY embedding <=> %(vec)s LIMIT %(limit)s",
                params,
            ).fetchall()
            kw_rows = []
            if params["tsquery"]:
                kw_rows = conn.execute(
                    f"SELECT {_COLUMNS}, 1 - (embedding <=> %(vec)s) AS sim, "
                    f"ts_rank_cd(content_tsv, to_tsquery('english', %(tsquery)s)) AS kw FROM rag_chunks "
                    f"WHERE {_FILTER_SQL} AND (content_tsv @@ to_tsquery('english', %(tsquery)s) "
                    f"OR mentioned_alarm_codes && %(codes)s::text[]) ORDER BY kw DESC LIMIT %(limit)s",
                    params,
                ).fetchall()

        for rank, row in enumerate(vec_rows, start=1):
            cand = candidates.setdefault(row[0], self._candidate(row))
            cand.similarity, cand.vec_rank = float(row[18]), rank
        for rank, row in enumerate(kw_rows, start=1):
            cand = candidates.setdefault(row[0], self._candidate(row))
            cand.similarity = float(row[18])
            cand.keyword, cand.kw_rank = float(row[19]), rank
        return _fuse(query, filters, candidates, top_k, alarm_codes, asset_ids, self._min_similarity)

    @staticmethod
    def _candidate(row) -> _Candidate:
        chunk = RetrievedChunk(
            chunk_id=row[0],
            doc_id=row[1],
            revision=row[2],
            title=row[3],
            doc_type=row[4],
            status=row[5],
            trust_level=row[6],
            section_number=row[7],
            section_title=row[8],
            heading_path=row[9],
            content=row[10],
            source_path=row[11],
            effective_date=row[12],
            suspected_injection=row[13],
            injection_signals=list(row[14]),
        )
        return _Candidate(chunk, row[15], row[16], row[17])


# -- In-memory ------------------------------------------------------------------------------


class InMemoryRetriever:
    """Loads and chunks the corpus from disk and ranks with numpy. Same contract as pgvector."""

    def __init__(
        self,
        document_path,
        embedder: Embedder,
        *,
        min_similarity: float = 0.62,
        candidates: int = 20,
        max_chars: int = 1500,
        overlap_chars: int = 200,
    ) -> None:
        self._embedder = embedder
        self._min_similarity = min_similarity
        self._candidates = candidates
        corpus = load_corpus(Path(document_path))
        self._rows: list[tuple[RetrievedChunk, dict]] = []
        texts: list[str] = []
        for doc in corpus.documents:
            meta = doc.metadata
            for c in chunk_document(doc, max_chars, overlap_chars):
                chunk = RetrievedChunk(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    revision=c.revision,
                    title=meta.title,
                    doc_type=meta.doc_type,
                    status=meta.status,
                    trust_level=meta.trust_level,
                    section_number=c.section_number,
                    section_title=c.section_title,
                    heading_path=c.heading_path,
                    content=c.content,
                    source_path=doc.source_path,
                    effective_date=meta.effective_date,
                    suspected_injection=c.suspected_injection,
                    injection_signals=list(c.injection_signals),
                )
                attrs = {
                    "sites": set(meta.sites),
                    "asset_classes": set(meta.asset_classes),
                    "doc_codes": meta.alarm_codes,
                    "doc_assets": meta.asset_ids,
                    "chunk_codes": c.mentioned_alarm_codes,
                    "terms": query_terms(f"{c.heading_path} {c.content}"),
                }
                self._rows.append((chunk, attrs))
                texts.append(build_embedding_text(doc, c))
        self._matrix = np.asarray(embedder.embed_documents(texts), dtype=np.float32) if texts else np.zeros((0, 1))
        self._doc_freq: dict[str, int] = {}
        for _, attrs in self._rows:
            for term in set(attrs["terms"]):
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

    def ping(self) -> dict:
        return {"documents": len({c.doc_id for c, _ in self._rows}), "chunks": len(self._rows)}

    def _passes(self, chunk: RetrievedChunk, attrs: dict, f: RetrievalFilters) -> bool:
        if chunk.status not in f.statuses:
            return False
        if f.doc_types and chunk.doc_type not in f.doc_types:
            return False
        if f.sites and attrs["sites"] and not attrs["sites"] & set(f.sites):
            return False
        if f.asset_classes and "all" not in attrs["asset_classes"] and not attrs["asset_classes"] & set(f.asset_classes):
            return False
        return not (f.exclude_untrusted and chunk.trust_level == "untrusted")

    def search(self, query, *, filters=None, top_k=6, alarm_codes=(), asset_ids=()) -> RetrievalResult:
        filters = filters or RetrievalFilters()
        qvec = np.asarray(self._embedder.embed_query(query), dtype=np.float32)
        norms = np.linalg.norm(self._matrix, axis=1) * (np.linalg.norm(qvec) or 1.0)
        sims = (self._matrix @ qvec) / np.where(norms == 0, 1.0, norms)
        terms = set(query_terms(query)) | {c.lower() for c in alarm_codes}
        n_docs = max(len(self._rows), 1)

        eligible = [i for i, (c, a) in enumerate(self._rows) if self._passes(c, a, filters)]
        by_vec = sorted(eligible, key=lambda i: -sims[i])[: self._candidates]
        kw_scores = {}
        for i in eligible:
            row_terms = self._rows[i][1]["terms"]
            score = sum(math.log(1 + n_docs / self._doc_freq.get(t, n_docs)) for t in terms if t in row_terms)
            if score > 0 or set(alarm_codes) & set(self._rows[i][1]["chunk_codes"]):
                kw_scores[i] = score
        by_kw = sorted(kw_scores, key=lambda i: -kw_scores[i])[: self._candidates]

        candidates: dict[str, _Candidate] = {}
        for rank, i in enumerate(by_vec, start=1):
            chunk, attrs = self._rows[i]
            cand = candidates.setdefault(
                chunk.chunk_id, _Candidate(_copy(chunk), attrs["doc_codes"], attrs["doc_assets"], attrs["chunk_codes"])
            )
            cand.similarity, cand.vec_rank = float(sims[i]), rank
        for rank, i in enumerate(by_kw, start=1):
            chunk, attrs = self._rows[i]
            cand = candidates.setdefault(
                chunk.chunk_id, _Candidate(_copy(chunk), attrs["doc_codes"], attrs["doc_assets"], attrs["chunk_codes"])
            )
            cand.similarity = float(sims[i])
            cand.keyword, cand.kw_rank = kw_scores[i], rank
        return _fuse(query, filters, candidates, top_k, alarm_codes, asset_ids, self._min_similarity)


def _copy(chunk: RetrievedChunk) -> RetrievedChunk:
    return replace(chunk, injection_signals=list(chunk.injection_signals), matched_alarm_codes=[], matched_asset_ids=[])
