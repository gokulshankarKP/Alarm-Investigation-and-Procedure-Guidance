import json

import httpx
import pytest

from rag.config import EmbeddingSettings
from rag.ingestion.embedder import EmbeddingError, OllamaEmbedder


def _settings(**overrides) -> EmbeddingSettings:
    values = {"dimension": 3, "batch_size": 2, "max_retries": 2, "document_prefix": "doc: "}
    return EmbeddingSettings(**{**values, **overrides})


def _embedder(handler, **overrides) -> OllamaEmbedder:
    client = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    return OllamaEmbedder(_settings(**overrides), client=client)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("rag.ingestion.embedder.time.sleep", lambda _: None)


def test_batches_requests_and_applies_document_prefix():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        seen.append(inputs)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]] * len(inputs)})

    vectors = _embedder(handler).embed_documents(["a", "b", "c"])

    assert len(vectors) == 3
    assert seen == [["doc: a", "doc: b"], ["doc: c"]]


def test_retries_transient_errors_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="loading model")
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0]]})

    assert _embedder(handler).embed_documents(["a"]) == [[1.0, 0.0, 0.0]]
    assert calls["n"] == 3


def test_gives_up_after_max_retries():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(EmbeddingError, match="after 3 attempts"):
        _embedder(handler).embed_documents(["a"])


def test_non_retryable_status_fails_immediately():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(EmbeddingError, match="HTTP 404"):
        _embedder(handler).embed_documents(["a"])
    assert calls["n"] == 1


def test_dimension_mismatch_is_rejected():
    def handler(request):
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    with pytest.raises(EmbeddingError, match="2-dim"):
        _embedder(handler).embed_documents(["a"])
