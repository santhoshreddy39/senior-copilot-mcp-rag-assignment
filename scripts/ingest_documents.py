#!/usr/bin/env python3
"""
Document ingestion command.

    python scripts/ingest_documents.py [--documents-dir rag/documents] [--index-path rag/index/retrieval_index.pkl]

Loads every ``*.md`` document in the corpus, extracts text, strips hidden
content (HTML comments) as a prompt-injection mitigation, chunks each
document by heading with metadata capture, flags any chunk that still
matches a known injection pattern, and persists the resulting chunk store so
the retriever can load it without re-parsing the corpus on every process
start.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.retrieval.index import RetrievalIndex
from rag.retrieval.retriever import DEFAULT_DOCUMENTS_DIR, DEFAULT_INDEX_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the document corpus and build the retrieval index.")
    parser.add_argument("--documents-dir", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    args = parser.parse_args()

    index = RetrievalIndex.build_from_documents(args.documents_dir)
    index.save(args.index_path)

    flagged = [c for c in index.chunks if c.injection_flagged]
    print(f"Ingested {len(list(args.documents_dir.glob('*.md')))} documents -> {len(index.chunks)} chunks")
    print(f"Index written to {args.index_path}")
    if flagged:
        print(f"WARNING: {len(flagged)} chunk(s) matched a prompt-injection pattern and were flagged:")
        for c in flagged:
            print(f"  - {c.chunk_id} ({c.title} / {c.section_heading})")


if __name__ == "__main__":
    main()
