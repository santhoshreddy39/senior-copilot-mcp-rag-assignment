# RAG Design

## Source document types

`rag/documents/*.md` — six Markdown files with YAML frontmatter, covering
every document type the assignment lists for this use case: an operating
procedure, a troubleshooting guide, a maintenance manual, a safety
instruction, an alarm philosophy document, and a ticket-resolution-notes
file (the last one also doubles as the prompt-injection test fixture — see
below). All are synthetic but written to match the simulator's asset names
and alarm types exactly, so retrieval and citation genuinely tie back to the
API data instead of being a disconnected demo corpus.

## Ingestion flow

`scripts/ingest_documents.py` -> `rag/ingestion/loader.py`:

1. **Text extraction**: read the `.md` file, split YAML frontmatter (parsed
   with `pyyaml`) from the body.
2. **Hidden-content stripping**: HTML/XML comments are removed from the body
   before any further processing (layer 1 of prompt-injection protection —
   see below).
3. **Chunking**: split on `#`/`##`/`###` headings, so each chunk is one
   semantically coherent section with a human-meaningful title (used
   directly in citations). A section longer than 900 characters is further
   split on paragraph boundaries with a small overlap, so no single chunk
   blows the retrieval context budget.
4. **Metadata capture**: every chunk carries `doc_id`, `title`, `doc_type`,
   `section_heading`, `applicable_assets`, `applicable_asset_types`, `tags`,
   `version`, `effective_date`, and `chunk_index` — sourced from the YAML
   frontmatter plus the heading structure.
5. **Injection scanning**: each chunk's text is scanned against a small set
   of known prompt-injection phrase patterns; a match sets
   `chunk.injection_flagged = True` (layer 1b).
6. Chunks are persisted to `rag/index/retrieval_index.pkl` (`RetrievalIndex.save`).

Run it with:
```bash
python scripts/ingest_documents.py
```

## Embedding model / retrieval method

**Hybrid lexical retrieval — TF-IDF cosine similarity + BM25 — with no model
download and no external API call.** `rag/retrieval/index.py` fits a
`scikit-learn` `TfidfVectorizer` (1-2 grams, English stopwords removed) and a
`rank_bm25.BM25Okapi` index over the same chunk texts at query time (fitting
28 short documents' worth of chunks is sub-millisecond, so there is no
meaningful cost to rebuilding on process start rather than pre-training a
model). The two scores are min-max normalized and blended 50/50.

This was a deliberate choice over calling an embedding API or downloading a
sentence-transformers model, documented in full in
`docs/design-decisions.md`: it keeps `docker compose up --build` fully
reproducible with zero external dependencies and zero API keys, which the
submission guidelines weight heavily ("setup works from a clean
environment"). The `Retriever` class (`rag/retrieval/retriever.py`) is the
only integration point the rest of the codebase uses — swapping in a
`sentence-transformers` + FAISS/Chroma backend, or an OpenAI-embeddings
backend, means implementing one new class with a `.score(query) -> ndarray`
method and does not touch the orchestrator, prompting, or GUI code at all.

## Vector database or index

None — `RetrievalIndex` keeps the fitted TF-IDF/BM25 structures in memory and
persists only the parsed `Chunk` list (not the fitted vectorizer) to a pickle
file; the vectorizer/BM25 index is refit from that chunk list on load, which
is effectively instant at this corpus size. A production deployment with a
larger, changing corpus would swap this for Chroma/FAISS/pgvector behind the
same `RetrievalIndex` interface without changing any calling code.

## Hybrid search

Yes — see "Embedding model / retrieval method" above. TF-IDF captures
n-gram/phrase similarity; BM25 captures term-frequency relevance with its own
saturation and length-normalization behavior. Blending both was empirically
more robust on this corpus than either alone (BM25 alone over-weighted
common domain terms like "alarm"/"pressure" that appear in nearly every
document; TF-IDF alone under-weighted exact phrase matches).

## Retrieval filtering

`Retriever.retrieve(query, asset_names=..., doc_types=...)` supports two
filters:
- `doc_types`: hard filter (chunks of other types are excluded entirely).
- `asset_names`: soft filter. A chunk whose `applicable_assets` doesn't
  include the resolved asset is *deprioritized* (score × 0.4) rather than
  dropped, because asset-agnostic documents (safety instructions, alarm
  philosophy) are frequently the most relevant citation for a "why" question
  and should not be filtered out just because they don't name a specific
  asset.

## Ranking / reranking

Results are sorted by the blended hybrid score, descending; no separate
reranking stage. See `docs/known-limitations.md` for where an LLM-based
reranker would be the natural next step.

## Citation construction

`RetrievedChunk.citation` -> `"<title> § <section_heading> (doc_id=<doc_id>)"`,
e.g. `"Operating Procedure OP-204 — Boiler Feed Pump Trains (Unit 3) §
4. High Vibration / High Bearing Temperature Response
(doc_id=boiler_feed_pump_operating_procedure)"`. This is what the GUI
displays, what appears in `[Doc: ...]` markers in template-synthesized
answers, and what an LLM is instructed to cite verbatim in
`apps/backend/copilot/prompting.py`.

## Low-confidence handling

`Retriever.retrieve` drops any candidate below `LOW_CONFIDENCE_THRESHOLD =
0.12` (hybrid score) before returning, and
`Retriever.is_low_confidence(results)` reports `True` when nothing survives.
The orchestrator surfaces this as `low_confidence_retrieval` in the API
response; the GUI shows an explicit warning instead of silently presenting a
shaky match as grounding evidence; the offline template synthesizer prints
an explicit "no document passages met the retrieval confidence threshold"
line instead of fabricating a citation.

## Prompt-injection protections

Two independent layers (see `rag/ingestion/security.py` and
`apps/backend/copilot/prompting.py`):

1. **Ingestion time**: HTML/XML comments are stripped from every document
   before chunking (a common place to hide text not meant for a human
   reader); remaining chunk text is scanned against known injection phrase
   patterns ("ignore previous instructions", "reveal the API key", "act as
   administrator", etc.) and flagged.
2. **Prompt-construction time**: every retrieved chunk is wrapped in an
   explicit `<retrieved_document>` tag in the LLM prompt, and the system
   prompt instructs the model, in plain terms, to treat that content as
   reference material to cite — never as an instruction — even if it reads
   as one, and to never reveal credentials or configuration values regardless
   of what a document says.

`rag/documents/ticket_resolution_notes.md` deliberately contains two planted
injection attempts (one inside an HTML comment demanding the model leak
`ALARM_API_TOKEN`/`LLM_API_KEY`, one in plain visible text framed as a
mis-pasted vendor email) so both layers have something real to catch — see
`rag/tests/test_ingestion.py` and
`tests/integration/test_orchestrator_workflow.py::test_prompt_injection_content_never_leaks_into_the_answer`.

## Index refresh process

`python scripts/ingest_documents.py` (or `make ingest`) re-parses every
document and overwrites `rag/index/retrieval_index.pkl`. The
`copilot-backend` docker-compose service runs this automatically on every
container start (see `docker-compose.yml`), so editing a document and
restarting the stack is sufficient — no manual reindex step is needed in the
common case.
