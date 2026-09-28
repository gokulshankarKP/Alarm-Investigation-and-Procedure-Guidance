from rag.config import PROJECT_ROOT
from rag.ingestion.chunker import build_embedding_text, chunk_document, split_text
from rag.ingestion.loader import load_corpus, parse_document

DOC = """---
doc_id: SOP-TST-001
title: Test Procedure
doc_type: sop
revision: A
status: active
trust_level: controlled
---

# Test Procedure

Intro paragraph before any section.

## 1. Scope

Covers BFP-101 and M-101. See SAF-001 and SOP-TST-001.

## 5. Alarm response

### 5.1 BFP-BRG-TEMP-H / HH — high bearing temperature

1. Check lube oil.

```
## not a heading inside a code fence
```
"""


def _chunks(max_chars=1500):
    return chunk_document(parse_document(DOC, "t.md"), max_chars=max_chars)


def test_one_chunk_per_section_and_empty_parent_headings_skipped():
    chunks = _chunks()

    assert [c.heading_path for c in chunks] == [
        "Preamble",
        "1. Scope",
        "5. Alarm response > 5.1 BFP-BRG-TEMP-H / HH — high bearing temperature",
    ]
    assert [c.chunk_id for c in chunks] == [f"SOP-TST-001::revA::{i:03d}" for i in range(3)]


def test_section_number_title_and_heading_line_in_content():
    chunk = _chunks()[2]

    assert chunk.section_number == "5.1"
    assert chunk.section_title.startswith("BFP-BRG-TEMP-H / HH")
    assert chunk.content.startswith("### 5.1 BFP-BRG-TEMP-H / HH")
    assert "## not a heading inside a code fence" in chunk.content


def test_extracts_alarm_codes_tags_and_references():
    scope, alarm = _chunks()[1], _chunks()[2]

    assert scope.mentioned_equipment_tags == ("BFP-101", "M-101")
    assert scope.referenced_doc_ids == ("SAF-001",)  # self-reference excluded
    assert alarm.mentioned_alarm_codes == ("BFP-BRG-TEMP-H", "BFP-BRG-TEMP-HH")


def test_split_text_respects_limit_and_block_boundaries():
    text = "\n\n".join(f"Paragraph {i} " + "x" * 80 for i in range(10))
    pieces = split_text(text, limit=300, overlap=0)

    assert len(pieces) > 1
    assert all(len(p) <= 300 for p in pieces)
    assert all(p.startswith("Paragraph") for p in pieces)


def test_long_sections_are_split_and_repeat_heading():
    long_doc = DOC.replace("1. Check lube oil.", "\n\n".join("Step text " + "y" * 150 for _ in range(8)))
    chunks = chunk_document(parse_document(long_doc, "t.md"), max_chars=400, overlap_chars=0)
    parts = [c for c in chunks if c.section_number == "5.1"]

    assert len(parts) > 1
    assert all(len(c.content) <= 400 for c in chunks)
    assert all(c.content.startswith("### 5.1") for c in parts)


def test_embedding_text_includes_document_context():
    doc = parse_document(DOC, "t.md")
    text = build_embedding_text(doc, chunk_document(doc)[1])

    assert text.startswith("Test Procedure (SOP-TST-001 rev A, sop)\nSection: 1. Scope")


def test_real_corpus_flags_only_the_injection_fixture():
    corpus = load_corpus(PROJECT_ROOT / "rag" / "documents")
    flagged = [c for d in corpus.documents for c in chunk_document(d) if c.suspected_injection]

    assert [c.doc_id for c in flagged] == ["VB-CMP-099"]
    assert "ignore_instructions" in flagged[0].injection_signals
