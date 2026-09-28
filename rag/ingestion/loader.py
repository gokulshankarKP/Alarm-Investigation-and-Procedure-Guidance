"""Load Markdown documents with YAML front matter from the corpus directory."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from rag.ingestion.models import DocumentMetadata, SourceDocument

logger = logging.getLogger(__name__)

_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)


class DocumentParseError(ValueError):
    """A corpus file could not be parsed into a valid document."""


@dataclass
class LoadResult:
    documents: list[SourceDocument] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)  # (source_path, reason)
    skipped: list[str] = field(default_factory=list)  # files without front matter (e.g. README)


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_document(text: str, source_path: str) -> SourceDocument:
    """Parse one document. Raises ``DocumentParseError`` on missing or invalid front matter."""
    text = _normalise(text)
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        raise DocumentParseError("missing YAML front matter")

    try:
        raw = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise DocumentParseError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(raw, dict):
        raise DocumentParseError("front matter must be a YAML mapping")

    try:
        metadata = DocumentMetadata.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
        raise DocumentParseError(f"invalid front matter: {problems}") from exc

    body = text[match.end() :].strip()
    if not body:
        raise DocumentParseError("document body is empty")

    return SourceDocument(
        metadata=metadata,
        body=body,
        source_path=source_path,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def load_corpus(root: Path) -> LoadResult:
    """Load every ``*.md`` document under ``root``.

    Files without front matter (such as the corpus README) are skipped. Invalid documents
    and duplicate ``(doc_id, revision)`` pairs are reported as failures instead of aborting
    the whole load.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"document directory not found: {root}")

    result = LoadResult()
    seen: dict[tuple[str, str], str] = {}

    for path in sorted(root.rglob("*.md")):
        source_path = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8-sig")

        if not _FRONT_MATTER_RE.match(_normalise(text)):
            logger.info("skip file=%s reason=no_front_matter", source_path)
            result.skipped.append(source_path)
            continue

        try:
            document = parse_document(text, source_path)
        except DocumentParseError as exc:
            logger.error("parse_failed file=%s error=%s", source_path, exc)
            result.failures.append((source_path, str(exc)))
            continue

        if document.key in seen:
            reason = f"duplicate doc_id/revision {document.key} (also in {seen[document.key]})"
            logger.error("parse_failed file=%s error=%s", source_path, reason)
            result.failures.append((source_path, reason))
            continue

        seen[document.key] = source_path
        result.documents.append(document)

    return result
