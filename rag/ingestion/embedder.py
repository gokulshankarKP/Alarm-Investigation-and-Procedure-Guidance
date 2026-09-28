"""Embedding providers.

The pipeline depends only on the ``Embedder`` protocol, so the Ollama implementation can
be swapped for another provider without touching ingestion or storage code.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from collections.abc import Sequence
from itertools import pairwise
from typing import Protocol

import httpx

from rag.config import EmbeddingSettings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """The embedding provider failed or returned an unusable response."""


class Embedder(Protocol):
    model: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Embeddings via Ollama's ``POST /api/embed`` endpoint, with batching, timeout and retry."""

    _RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(self, settings: EmbeddingSettings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self.model = settings.model
        self.dimension = settings.dimension
        self._client = client or httpx.Client(base_url=settings.base_url, timeout=settings.timeout_s)

    def __enter__(self) -> OllamaEmbedder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prefix = self._settings.document_prefix
        return self._embed_all([f"{prefix}{t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed_all([f"{self._settings.query_prefix}{text}"])[0]

    def _embed_all(self, texts: list[str]) -> list[list[float]]:
        size = self._settings.batch_size
        vectors: list[list[float]] = []
        for start in range(0, len(texts), size):
            vectors.extend(self._embed_batch(texts[start : start + size]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        attempts = self._settings.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = self._client.post("/api/embed", json={"model": self.model, "input": batch})
            except httpx.TransportError as exc:  # connection refused, timeout, ...
                error: str = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    return self._parse(response, expected=len(batch))
                error = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in self._RETRYABLE_STATUS:
                    raise EmbeddingError(f"embedding request failed ({error})")

            if attempt == attempts:
                raise EmbeddingError(f"embedding request failed after {attempts} attempts ({error})")
            delay = min(2 ** (attempt - 1), 10)
            logger.warning(
                "embed_retry model=%s attempt=%d/%d delay_s=%d error=%s",
                self.model,
                attempt,
                attempts,
                delay,
                error,
            )
            time.sleep(delay)
        raise AssertionError("unreachable")

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            vectors = response.json()["embeddings"]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError("embedding response has no 'embeddings' field") from exc
        if len(vectors) != expected:
            raise EmbeddingError(f"expected {expected} embeddings, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(f"model '{self.model}' returned {len(vector)}-dim vectors but EMBEDDING_DIMENSION={self.dimension}")
        return vectors


class HashingEmbedder:
    """Deterministic, dependency-free embedder (feature hashing of word uni/bi-grams).

    Lexical rather than semantic; used for CI and tests where no embedding server is
    available. Never mix vectors from different providers: the model name is stored with
    every document, so switching provider triggers re-embedding.
    """

    _WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
    _STOP = frozenset(
        [
            "a",
            "an",
            "the",
            "and",
            "or",
            "of",
            "to",
            "in",
            "on",
            "for",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "what",
            "which",
            "why",
            "how",
            "who",
            "when",
            "where",
            "this",
            "that",
            "these",
            "those",
            "with",
            "by",
            "at",
            "from",
            "it",
            "its",
            "as",
            "do",
            "does",
            "did",
            "should",
            "can",
            "could",
            "would",
            "will",
            "i",
            "we",
            "you",
            "me",
            "my",
            "our",
            "your",
            "there",
            "any",
            "all",
            "about",
            "into",
            "than",
            "then",
            "so",
            "if",
            "not",
            "no",
            "yes",
            "please",
            "show",
            "tell",
            "give",
        ]
    )

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension
        self.model = f"hash-{dimension}"

    def _vector(self, text: str) -> list[float]:
        words = [w for w in self._WORD.findall(text.lower()) if w not in self._STOP]
        features = words + [f"{a} {b}" for a, b in pairwise(words)]
        vec = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            vec[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def close(self) -> None:
        pass


def create_embedder(settings: EmbeddingSettings) -> Embedder:
    if settings.provider == "hash":
        return HashingEmbedder(settings.dimension)
    return OllamaEmbedder(settings)
