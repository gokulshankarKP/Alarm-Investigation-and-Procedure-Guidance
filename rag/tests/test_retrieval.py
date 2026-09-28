"""Retrieval tests on the in-memory backend (same ranking/filters as pgvector) with the hashing embedder."""

import pytest

from rag.config import PROJECT_ROOT
from rag.ingestion.embedder import HashingEmbedder
from rag.retrieval import InMemoryRetriever, RetrievalFilters


@pytest.fixture(scope="module")
def retriever():
    return InMemoryRetriever(PROJECT_ROOT / "rag" / "documents", HashingEmbedder(768), min_similarity=0.1)


def test_relevant_section_ranks_first_for_troubleshooting_question(retriever):
    res = retriever.search(
        "Why are compressor discharge pressure alarms repeatedly occurring?",
        alarm_codes=["CMP-DISCH-P-H"],
        filters=RetrievalFilters(exclude_untrusted=True),
    )
    assert res.chunks[0].doc_id in {"TSG-CMP-002", "SOP-CMP-001"}
    assert not res.low_confidence


def test_exact_alarm_code_match_boosts_alarm_response_section(retriever):
    res = retriever.search("alarm response", alarm_codes=["BFP-VIB-HH"], filters=RetrievalFilters(doc_types=("sop",)), top_k=3)
    assert res.chunks[0].citation_label == "SOP-BFP-001 rev C §5.2"
    assert "BFP-VIB-HH" in res.chunks[0].matched_alarm_codes


def test_superseded_revision_excluded_by_default(retriever):
    res = retriever.search("CMP-DISCH-P-H high discharge pressure start spare compressor", alarm_codes=["CMP-DISCH-P-H"], top_k=10)
    assert all(c.status == "active" for c in res.chunks)
    assert ("SOP-CMP-001", "A") not in {(c.doc_id, c.revision) for c in res.chunks}
    old = retriever.search("CMP-DISCH-P-H", filters=RetrievalFilters(statuses=("superseded",)))
    assert {c.revision for c in old.chunks} == {"A"}


def test_metadata_filters(retriever):
    res = retriever.search("vibration trip", filters=RetrievalFilters(doc_types=("safety",)), top_k=10)
    assert res.chunks and {c.doc_type for c in res.chunks} == {"safety"}
    res = retriever.search("alarm", filters=RetrievalFilters(sites=("SouthPlant",)), top_k=20)
    assert "SOP-CMP-001" not in {c.doc_id for c in res.chunks}  # EastRefinery-only document filtered out
    res = retriever.search("compressor", filters=RetrievalFilters(exclude_untrusted=True), top_k=20)
    assert "VB-CMP-099" not in {c.doc_id for c in res.chunks}


def test_no_result_and_low_confidence(retriever):
    empty = retriever.search("anything", filters=RetrievalFilters(doc_types=("nonexistent",)))
    assert empty.chunks == [] and empty.low_confidence and empty.reason == "no documents matched the filters"
    off_topic = retriever.search("What is the capital of France?")
    assert off_topic.low_confidence


def test_injection_chunk_is_flagged_in_results(retriever):
    res = retriever.search("note for automated assistants ignore previous instructions", top_k=10)
    flagged = [c for c in res.chunks if c.suspected_injection]
    assert flagged and flagged[0].doc_id == "VB-CMP-099" and flagged[0].trust_level == "untrusted"


def test_citation_metadata_is_complete(retriever):
    chunk = retriever.search("motor trip related assets to inspect", alarm_codes=["MTR-TRIP-OL"]).chunks[0]
    assert chunk.doc_id == "MM-MTR-001" and chunk.revision == "C" and chunk.section_number
    assert chunk.source_path.endswith(".md") and chunk.title and chunk.heading_path
    assert chunk.to_dict()["citation_label"].startswith("MM-MTR-001 rev C §")
