"""Heading-aware Markdown chunking.

Strategy
--------
* Every ``##``/``###``/... heading starts a new section; the ``#`` title is dropped
  (it is already in the document metadata). Each section becomes one chunk, so a
  citation can point at an exact section such as ``SOP-BFP-001 §5.2``.
* Headings with no body of their own (e.g. ``## 5. Alarm response`` directly followed
  by ``### 5.1 ...``) produce no chunk but remain in the ``heading_path`` of their children.
* Sections longer than ``max_chars`` are split on blank-line boundaries (paragraphs,
  whole tables, whole lists), then on lines if a single block is still too long. The
  heading line is repeated on each part, and a short trailing block is carried over as
  overlap.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

from rag.ingestion.injection import detect_injection_signals
from rag.ingestion.models import Chunk, SourceDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SECTION_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")

# Alarm codes follow <ASSET-CLASS>-<MEASUREMENT>-<LEVEL>, e.g. BFP-VIB-HH, CMP-SURGE, DA-LVL-L.
# "BFP-BRG-TEMP-H / HH" is shorthand for BFP-BRG-TEMP-H and BFP-BRG-TEMP-HH.
_ALARM_CODE_RE = re.compile(r"(?<![\w-])((?:BFP|DA|CMP|MTR|BLR)(?:-[A-Z]+)+)(?![\w-])((?:\s*/\s*(?:LL|L|HH|H|TRIP)(?![\w-]))*)")
_DOC_PREFIXES = r"(?:SOP|TSG|MM|SAF|ALM|VB)"
# Document references, e.g. SOP-BFP-001, ALM-PHIL-001, SAF-002.
_DOC_REF_RE = re.compile(rf"(?<![\w-]){_DOC_PREFIXES}(?:-[A-Z]+)*-\d{{3}}(?![\w-])")
# Equipment tags, e.g. BFP-101, K-201, M-501, PCV-210 (excluding document ids).
_EQUIPMENT_TAG_RE = re.compile(rf"(?<![\w-])(?!{_DOC_PREFIXES}-)[A-Z]{{1,4}}-\d{{3}}(?![\w-])")

PREAMBLE_TITLE = "Preamble"


@dataclass
class _Section:
    path: tuple[str, ...]  # heading texts from level 2 downwards
    heading_line: str | None
    lines: list[str]

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()


def _split_sections(body: str) -> list[_Section]:
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    current = _Section(path=(), heading_line=None, lines=[])
    in_fence = False

    for line in body.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING_RE.match(line)
        if heading is None:
            current.lines.append(line)
            continue

        level, text = len(heading.group(1)), heading.group(2).strip()
        if level == 1:
            continue  # document title
        sections.append(current)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
        current = _Section(path=tuple(t for _, t in stack), heading_line=line.strip(), lines=[])

    sections.append(current)
    return [s for s in sections if s.body]


def _hard_split(block: str, limit: int) -> list[str]:
    """Split an oversized block on line boundaries (and inside over-long lines as a last resort)."""
    parts: list[str] = []
    current = ""
    for line in block.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def split_text(text: str, limit: int, overlap: int) -> list[str]:
    """Split ``text`` into pieces of at most ``limit`` characters on natural boundaries."""
    if len(text) <= limit:
        return [text]

    units: list[str] = []
    for block in (b.strip() for b in re.split(r"\n[ \t]*\n", text)):
        if not block:
            continue
        units.extend([block] if len(block) <= limit else _hard_split(block, limit))

    pieces: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and len("\n\n".join([*current, unit])) > limit:
            pieces.append("\n\n".join(current))
            tail = current[-1]
            carry = len(tail) <= overlap and len(tail) + 2 + len(unit) <= limit
            current = [tail, unit] if carry else [unit]
        else:
            current.append(unit)
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _extract_alarm_codes(text: str) -> list[str]:
    codes: list[str] = []
    for match in _ALARM_CODE_RE.finditer(text):
        code, alternates = match.group(1), match.group(2)
        codes.append(code)
        stem = code.rsplit("-", 1)[0]
        codes.extend(f"{stem}-{level.strip()}" for level in alternates.split("/")[1:])
    return codes


def _unique(values: list[str], exclude: Collection[str] = frozenset()) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v not in exclude))


def chunk_document(document: SourceDocument, max_chars: int = 1500, overlap_chars: int = 200) -> list[Chunk]:
    meta = document.metadata
    chunks: list[Chunk] = []

    for section in _split_sections(document.body):
        heading_text = section.path[-1] if section.path else PREAMBLE_TITLE
        number_match = _SECTION_NUMBER_RE.match(heading_text)
        section_number = number_match.group(1) if number_match else None
        section_title = number_match.group(2) if number_match else heading_text
        heading_path = " > ".join(section.path) if section.path else PREAMBLE_TITLE

        prefix = f"{section.heading_line}\n\n" if section.heading_line else ""
        limit = max(max_chars - len(prefix), 100)
        for piece in split_text(section.body, limit, overlap_chars):
            content = f"{prefix}{piece}"
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{meta.doc_id}::rev{meta.revision}::{index:03d}",
                    doc_id=meta.doc_id,
                    revision=meta.revision,
                    chunk_index=index,
                    section_number=section_number,
                    section_title=section_title,
                    heading_path=heading_path,
                    content=content,
                    mentioned_alarm_codes=_unique(_extract_alarm_codes(content)),
                    mentioned_equipment_tags=_unique(_EQUIPMENT_TAG_RE.findall(content)),
                    referenced_doc_ids=_unique(_DOC_REF_RE.findall(content), exclude={meta.doc_id}),
                    injection_signals=detect_injection_signals(content),
                )
            )
    return chunks


def build_embedding_text(document: SourceDocument, chunk: Chunk) -> str:
    """Text sent to the embedding model: document + section context, then the chunk content."""
    meta = document.metadata
    return f"{meta.title} ({meta.doc_id} rev {meta.revision}, {meta.doc_type})\nSection: {chunk.heading_path}\n\n{chunk.content}"
