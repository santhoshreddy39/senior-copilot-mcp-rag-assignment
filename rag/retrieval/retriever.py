"""
High-level retrieval API used by the copilot orchestration layer. Wraps
RetrievalIndex with metadata filtering, a low-confidence cutoff, and citation
construction so the rest of the codebase never touches TF-IDF/BM25 directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag.ingestion.loader import Chunk
from rag.retrieval.index import RetrievalIndex

DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[1] / "index" / "retrieval_index.pkl"
DEFAULT_DOCUMENTS_DIR = Path(__file__).resolve().parents[1] / "documents"

# Below this hybrid score, a match is treated as "no confident result" rather
# than being surfaced to the user as grounding evidence — a weak lexical
# match dressed up as a citation is worse than admitting nothing relevant
# was found.
LOW_CONFIDENCE_THRESHOLD = 0.12


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float

    @property
    def citation(self) -> str:
        return f"{self.chunk.title} § {self.chunk.section_heading} (doc_id={self.chunk.doc_id})"

    def to_dict(self) -> dict:
        return {
            "doc_id": self.chunk.doc_id,
            "title": self.chunk.title,
            "section_heading": self.chunk.section_heading,
            "doc_type": self.chunk.doc_type,
            "text": self.chunk.text,
            "score": round(float(self.score), 4),
            "citation": self.citation,
            "source_path": self.chunk.source_path,
            "injection_flagged": self.chunk.injection_flagged,
        }


class Retriever:
    def __init__(self, index: RetrievalIndex | None = None):
        self._index = index or self._load_or_build_default_index()

    @staticmethod
    def _load_or_build_default_index() -> RetrievalIndex:
        if DEFAULT_INDEX_PATH.exists():
            return RetrievalIndex.load(DEFAULT_INDEX_PATH)
        return RetrievalIndex.build_from_documents(DEFAULT_DOCUMENTS_DIR)

    def retrieve(
        self, query: str, *, asset_names: list[str] | None = None, doc_types: list[str] | None = None, top_k: int = 4
    ) -> list[RetrievedChunk]:
        if not query or not query.strip():
            return []
        scores = self._index.score(query)
        candidates: list[RetrievedChunk] = []
        for chunk, score in zip(self._index.chunks, scores):
            if doc_types and chunk.doc_type not in doc_types:
                continue
            if asset_names:
                relevant = (
                    any(a in chunk.applicable_assets for a in asset_names)
                    or not chunk.applicable_assets  # asset-agnostic docs (safety, philosophy) always eligible
                )
                if not relevant:
                    # Still eligible, but scored down — an asset-agnostic-looking mismatch
                    # shouldn't be dropped outright, only deprioritized.
                    score = score * 0.4
            candidates.append(RetrievedChunk(chunk=chunk, score=score))

        candidates.sort(key=lambda c: c.score, reverse=True)
        top = candidates[:top_k]
        # Low-confidence handling: drop chunks below threshold rather than
        # presenting a shaky match to the user as grounding evidence.
        return [c for c in top if c.score >= LOW_CONFIDENCE_THRESHOLD]

    def is_low_confidence(self, results: list[RetrievedChunk]) -> bool:
        return len(results) == 0
