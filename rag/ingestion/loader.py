"""
Document loading, text extraction, and heading-aware chunking with metadata
capture. Supported source format: Markdown with YAML frontmatter (the sample
corpus in rag/documents/). A PDF/DOCX extractor can be added behind the same
``Chunk`` interface without touching the retriever — see docs/rag-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .security import scan_for_injection, strip_hidden_content

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$", re.MULTILINE)

MAX_CHUNK_CHARS = 900
CHUNK_OVERLAP_CHARS = 120


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    section_heading: str
    text: str
    source_path: str
    applicable_assets: list[str] = field(default_factory=list)
    applicable_asset_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: str = ""
    effective_date: str = ""
    chunk_index: int = 0
    injection_flagged: bool = False


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2)


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Splits markdown body into (heading, section_text) pairs on ## headings."""
    matches = list(HEADING_RE.finditer(body))
    if not matches:
        return [("", body.strip())]
    sections = []
    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((heading, body[start:end].strip()))
    return sections


def _sub_chunk(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Splits an over-long section into overlapping character-window chunks on paragraph
    boundaries where possible, so no single chunk blows the retrieval context budget."""
    if len(text) <= max_chars:
        return [text]
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            current = current[-overlap:] + "\n\n" + para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def load_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    body, _ = strip_hidden_content(body)  # layer 1 of prompt-injection protection

    doc_id = path.stem
    title = meta.get("title", doc_id)
    doc_type = meta.get("doc_type", "unknown")
    applicable_assets = meta.get("applicable_assets", []) or []
    applicable_asset_types = meta.get("applicable_asset_types", []) or []
    tags = meta.get("tags", []) or []
    version = str(meta.get("version", ""))
    effective_date = str(meta.get("effective_date", ""))

    chunks: list[Chunk] = []
    chunk_index = 0
    for heading, section_text in _split_sections(body):
        if not section_text.strip():
            continue
        for sub in _sub_chunk(section_text):
            injection_hits = scan_for_injection(sub)
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}::{chunk_index}",
                    doc_id=doc_id,
                    title=title,
                    doc_type=doc_type,
                    section_heading=heading or title,
                    text=sub,
                    source_path=str(path),
                    applicable_assets=applicable_assets,
                    applicable_asset_types=applicable_asset_types,
                    tags=tags,
                    version=version,
                    effective_date=effective_date,
                    chunk_index=chunk_index,
                    injection_flagged=bool(injection_hits),
                )
            )
            chunk_index += 1
    return chunks


def load_corpus(documents_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(documents_dir.glob("*.md")):
        chunks.extend(load_document(path))
    return chunks
