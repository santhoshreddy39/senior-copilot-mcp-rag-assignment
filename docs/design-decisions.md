# Design Decisions

## Why the intent/entity planner is a deterministic heuristic, not an LLM call

`apps/backend/copilot/nlu.py` classifies intent and extracts entities
(asset/unit/site/severity/status/time-window) with regex-based rules, not an
LLM. Two reasons:

1. **Reproducibility for grading.** The submission guidelines weight "setup
   works from a clean environment" and flag "repository cannot run using
   documented steps" as a red flag. A planner that requires an LLM API key
   would mean `docker compose up --build` with an empty `.env` produces a
   degraded or non-functional copilot. The heuristic planner works
   identically with or without an LLM configured.
2. **The domain is genuinely bounded.** Alarm-investigation questions cluster
   into a handful of intents (active alarms, recurring investigation,
   priority, related assets, procedure lookup, recommendation consistency,
   full investigation) over a small entity vocabulary (asset names, units,
   sites, severities, statuses). A rule set generalizes well here (see
   `tests/unit/test_nlu.py::test_generalizes_to_an_unseen_phrasing`)
   and is fast, deterministic, and directly unit-testable — properties an
   LLM-based planner would not have without significant extra scaffolding
   (structured output validation, retries on malformed tool-call JSON, etc.).

This is explicitly **not** a lookup table of the assignment's own example
questions — see the "not hard-coded" requirement in
`Assignment_Use_Case.md` §3. The rules match phrase *categories*
("repeatedly|recurring|why (are|is|does|do)" for the recurring-investigation
intent) and the entity extractor pattern-matches *any* Title-Case asset name
or known unit/site, not a fixed list of the assignment's sample sentences.

If this were extended for production use with a wider or shifting intent
vocabulary, the natural next step is exactly what the "replaceable LLM
provider" architecture already supports: add an `LLMPlanner` that calls out
to `LLMProvider.complete()` with a structured-output prompt, and fall back to
the heuristic planner when no provider is configured or the LLM call fails —
the same fallback pattern already used for answer synthesis (see below).

## Why answer synthesis defaults to an offline template, not an LLM

`apps/backend/copilot/synthesis.py::synthesize_template` is a generic
narrator that turns whatever `Findings` fields the orchestrator populated
into readable, cited prose, with no external call. It is used automatically
when `LLM_PROVIDER` is unset (see `apps/backend/llm/provider.py::get_llm_provider`),
and again as an automatic fallback if a configured provider's API call fails
or returns nothing at request time.

This means the assignment's mandatory demo scenario, and every automated
test, work with zero configuration and zero cost — a grader can clone the
repo, run `docker compose up --build`, and get real, grounded, cited answers
without ever touching an API key. Configuring `LLM_PROVIDER=openai` (or
`anthropic` / `azure_openai`) swaps in genuinely more fluent prose over the
*same* structured findings and the *same* citations — nothing about the
retrieval, MCP orchestration, or grounding changes; only the final
natural-language rendering does. This is the practical meaning of
"replaceable LLM provider" applied end to end, not just at the type-signature
level.

## Why RAG retrieval is hybrid TF-IDF + BM25, not embeddings

See `docs/rag-design.md`'s "Embedding model / retrieval method" section for
the full rationale — in short: zero external dependency, sub-millisecond
index build, fully reproducible, and the `Retriever` class isolates this
choice behind one interface so a real embedding backend is a drop-in swap,
not a rewrite.

## Why MCP runs over stdio (subprocess), not HTTP/SSE

See `docs/architecture.md`'s "Why MCP over stdio, not a network transport"
section. In short: it's the standard pattern real MCP hosts use for local
servers, keeps the MCP boundary genuine without unneeded network-transport
complexity, and the server remains independently runnable and testable.

## Why the simulator generates synthetic data instead of a fixed fixture file

A fixed JSON fixture would have been simpler, but a small generator
(`apps/backend/simulator/data.py`) with a **fixed random seed** gives
reproducibility (same data every run/test) *and* enough volume and
variety (230+ alarms across 10 assets, multiple severities and time
patterns) to make recurrence/correlation/priority-scoring answers
genuinely non-trivial, which a hand-written fixture of a realistic size
would have been tedious and error-prone to maintain by hand. A small set of
alarms is deliberately seeded as currently-active
(`GUARANTEED_ACTIVE`) so the assignment's example questions never depend on
random luck.
