"""
Retrieval index: builds and persists a hybrid lexical index (TF-IDF cosine +
BM25) over the ingested chunks. No network access or model download is
required to build or query this index, which keeps ``docker compose up``
fully reproducible out of the box. See docs/rag-design.md for the rationale
and for how an embedding-based backend can be swapped in behind the same
``Retriever`` interface (rag/retrieval/retriever.py) if a stronger semantic
match is needed in production.
"""

from __future__ import annotations

import pickle
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from rag.ingestion.loader import Chunk, load_corpus

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    # Stopwords are filtered for BOTH the corpus and the query (same function used for
    # both) so common function words don't dominate BM25 scores on off-topic queries —
    # without this, a query like "tell me about zebras and rainbows" would still score
    # moderately against every chunk purely on "about"/"and", defeating low-confidence
    # detection.
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in ENGLISH_STOP_WORDS and len(t) > 1]


class RetrievalIndex:
    """Holds the chunk store plus a fitted TF-IDF vectorizer and BM25 index."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        corpus_texts = [f"{c.title} {c.section_heading} {c.text}" for c in chunks]
        self._tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self._tfidf_matrix = self._tfidf.fit_transform(corpus_texts) if chunks else None
        tokenized = [_tokenize(t) for t in corpus_texts]
        self._bm25 = BM25Okapi(tokenized) if chunks else None

    def score(self, query: str) -> np.ndarray:
        """Blended hybrid score: 0.5 * normalized TF-IDF cosine + 0.5 * normalized BM25."""
        if not self.chunks:
            return np.array([])
        tfidf_vec = self._tfidf.transform([query])
        tfidf_scores = cosine_similarity(tfidf_vec, self._tfidf_matrix)[0]
        bm25_scores = np.array(self._bm25.get_scores(_tokenize(query)))

        def _normalize(arr: np.ndarray) -> np.ndarray:
            max_val = arr.max() if arr.size else 0.0
            return arr / max_val if max_val > 0 else arr

        return 0.5 * _normalize(tfidf_scores) + 0.5 * _normalize(bm25_scores)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"chunks": [asdict(c) for c in self.chunks]}, f)

    @classmethod
    def load(cls, path: Path) -> "RetrievalIndex":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        chunks = [Chunk(**c) for c in payload["chunks"]]
        return cls(chunks)

    @classmethod
    def build_from_documents(cls, documents_dir: Path) -> "RetrievalIndex":
        return cls(load_corpus(documents_dir))
