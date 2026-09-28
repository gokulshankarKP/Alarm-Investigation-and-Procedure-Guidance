"""CLI: ``python -m rag.ingestion [--rebuild] [--prune] [--dry-run] [--docs PATH]``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rag.config import IngestionSettings, RagSettings
from rag.ingestion.pipeline import IngestionReport, run_ingestion


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m rag.ingestion",
        description="Chunk, embed and index the RAG document corpus into PostgreSQL/pgvector.",
    )
    parser.add_argument("--docs", type=Path, help="corpus directory (default: DOCUMENT_PATH or rag/documents)")
    parser.add_argument("--rebuild", action="store_true", help="drop and recreate the index tables first")
    parser.add_argument("--prune", action="store_true", help="remove indexed documents no longer in the corpus")
    parser.add_argument("--dry-run", action="store_true", help="parse and chunk only; no embedding or DB writes")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def _print_report(report: IngestionReport) -> None:
    print("\n=== Ingestion summary ===")
    print(f"documents discovered : {report.discovered}")
    print(f"ingested             : {len(report.ingested)}")
    print(f"unchanged (skipped)  : {len(report.unchanged)}")
    print(f"pruned               : {len(report.pruned)}")
    print(f"chunks written       : {report.chunks_written}")
    print(f"injection-flagged    : {len(report.flagged_chunks)} {report.flagged_chunks or ''}")
    print(f"failed               : {len(report.failed)}")
    for path, reason in report.failed:
        print(f"  - {path}: {reason}")
    print(f"duration             : {report.duration_s:.1f}s")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ingestion = IngestionSettings.model_validate({"DOCUMENT_PATH": args.docs}) if args.docs else None
    settings = RagSettings(ingestion=ingestion)

    try:
        report = run_ingestion(settings, rebuild=args.rebuild, prune=args.prune, dry_run=args.dry_run)
    except Exception as exc:
        logging.getLogger("rag.ingestion").error("ingestion_aborted error=%s", exc)
        return 2

    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
