from pathlib import Path

import pytest

from rag.config import PROJECT_ROOT
from rag.ingestion.loader import DocumentParseError, load_corpus, parse_document

CORPUS = PROJECT_ROOT / "rag" / "documents"

VALID = """---
doc_id: SOP-TST-001
title: Test Procedure
doc_type: sop
revision: 1
status: active
effective_date: 2026-01-01
asset_classes: [pump]
asset_ids: []
alarm_codes: [TST-VIB-H]
sites: [NorthPlant]
trust_level: controlled
---

# Test Procedure

## 1. Scope

Body text.
"""


def test_parse_document_reads_front_matter_and_body():
    doc = parse_document(VALID, "procedures/test.md")

    assert doc.metadata.doc_id == "SOP-TST-001"
    assert doc.metadata.revision == "1"  # YAML int coerced to str
    assert doc.metadata.asset_ids == ()
    assert doc.metadata.alarm_codes == ("TST-VIB-H",)
    assert doc.body.startswith("# Test Procedure")
    assert "doc_id" not in doc.body


def test_content_hash_ignores_line_ending_style():
    assert parse_document(VALID, "a.md").content_hash == parse_document(VALID.replace("\n", "\r\n"), "a.md").content_hash


def test_missing_front_matter_is_rejected():
    with pytest.raises(DocumentParseError, match="front matter"):
        parse_document("# Just markdown\n", "x.md")


def test_invalid_enum_value_is_rejected():
    with pytest.raises(DocumentParseError, match="trust_level"):
        parse_document(VALID.replace("trust_level: controlled", "trust_level: whatever"), "x.md")


def test_load_corpus_reports_bad_files_and_duplicates(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Corpus readme\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(VALID, encoding="utf-8")
    (tmp_path / "b.md").write_text(VALID, encoding="utf-8")  # same doc_id + revision
    (tmp_path / "c.md").write_text(VALID.replace("status: active", "status: draft"), encoding="utf-8")

    result = load_corpus(tmp_path)

    assert [d.source_path for d in result.documents] == ["a.md"]
    assert result.skipped == ["README.md"]
    assert {path for path, _ in result.failures} == {"b.md", "c.md"}


def test_real_corpus_loads_with_expected_metadata():
    result = load_corpus(CORPUS)
    by_key = {d.key: d for d in result.documents}

    assert not result.failures
    assert len(result.documents) == 11
    # Both revisions of SOP-CMP-001 are kept; retrieval filters on status.
    assert by_key[("SOP-CMP-001", "A")].metadata.status == "superseded"
    assert by_key[("SOP-CMP-001", "B")].metadata.status == "active"
    assert by_key[("VB-CMP-099", "1")].metadata.trust_level == "untrusted"
