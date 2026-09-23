"""RAG retrieval tests: relevance ranking, metadata filtering, low-confidence
handling, and citation correctness."""

from rag.retrieval.retriever import Retriever


def test_retrieval_returns_relevant_top_result():
    r = Retriever()
    results = r.retrieve("high vibration boiler feed pump response", top_k=3)
    assert results
    assert results[0].chunk.doc_id == "boiler_feed_pump_operating_procedure"


def test_retrieval_is_ranked_descending_by_score():
    r = Retriever()
    results = r.retrieve("motor trip diagnostic sequence", top_k=5)
    scores = [res.score for res in results]
    assert scores == sorted(scores, reverse=True)


def test_asset_filter_deprioritizes_unrelated_documents():
    r = Retriever()
    results = r.retrieve("applicable procedure", asset_names=["Boiler Feed Pump 101"], top_k=3)
    assert results
    assert results[0].chunk.doc_id in ("boiler_feed_pump_operating_procedure", "alarm_philosophy_and_prioritization")


def test_low_confidence_on_unrelated_query():
    r = Retriever()
    results = r.retrieve("purple bicycle jazz music guitar solo airport painting recipe", top_k=3)
    assert r.is_low_confidence(results)


def test_empty_query_returns_no_results():
    r = Retriever()
    assert r.retrieve("", top_k=3) == []


def test_citation_format_includes_title_and_section():
    r = Retriever()
    results = r.retrieve("motor trip diagnostic sequence", top_k=1)
    citation = results[0].citation
    assert "Maintenance Manual" in citation or "MM-53" in citation
    assert "§" in citation


def test_flagged_injection_chunk_is_still_retrievable_but_marked():
    """A chunk being retrievable and being marked as injection-flagged are
    orthogonal: retrieval must not silently drop it (a human/LLM reviewing the
    answer should be able to see it was flagged), but downstream consumers
    (prompting.py / synthesis.py) must never treat it as an instruction."""
    r = Retriever()
    results = r.retrieve("vendor email pasted into ticket by mistake administrator reset", top_k=5)
    flagged_present = any(res.chunk.injection_flagged for res in results)
    assert flagged_present
