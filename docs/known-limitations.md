# Known Limitations

- **Docker build was not executed inside the development sandbox used to
  build this project** — that sandbox has no Docker daemon available. The
  `Dockerfile` and `docker-compose.yml` were validated with `docker compose
  config` (full YAML/variable resolution passes) and every service's exact
  command was run and verified manually outside Docker (`uvicorn
  apps.backend.simulator.main:app`, `uvicorn apps.backend.main:app`,
  `streamlit run apps/frontend/app.py`, with the real dependency versions
  pinned in `requirements.txt`). **Run `docker compose up --build` once
  yourself before submitting** to confirm the container build end to end —
  it should work from these files, but it has not been confirmed inside an
  actual container.
- **Intent/entity extraction is a bounded heuristic**, not an LLM-based
  planner (see `docs/design-decisions.md`). It handles the assignment's
  question shapes and reasonable variations well, but an unusual phrasing
  outside its ~7 intent categories falls through to the generic
  `FULL_INVESTIGATION` plan rather than a tailored one. An `LLMPlanner`
  behind the same interface is the natural extension.
- **Asset disambiguation is "closest match, with a warning"**, not a
  clarifying follow-up question. If a query matches multiple assets (e.g.
  "the compressor" when two compressors exist), the orchestrator picks the
  top search result and surfaces a warning explaining the ambiguity, rather
  than asking the user to pick one. A true multi-turn clarification flow
  would need conversation state, which the current single-turn `/chat`
  endpoint doesn't carry.
- **RAG retrieval is lexical (TF-IDF + BM25), not semantic embeddings** (see
  `docs/rag-design.md`). This is deliberate for reproducibility, but it means
  a document that expresses the right concept in very different wording than
  the query could be missed. The `Retriever` interface makes swapping in an
  embedding backend a contained change.
- **No reranking stage.** Results are ordered by the blended hybrid score
  directly. An LLM-based reranker (score the top ~10 candidates for
  relevance to the specific question) would improve precision on ambiguous
  queries.
- **Not every simulator endpoint is exposed as an MCP tool.** `/alarms/trends`,
  `/alarms/flood-analysis`, `/alarms/rationalization-candidates`, and the
  `/calculation-code/*` pair exist and are tested at the API layer but have
  no corresponding MCP tool yet — see `docs/mcp-tool-catalog.md`'s "Not
  exposed through MCP" section for the reasoning and the extension path.
- **Conversation has no memory across turns.** Each `/chat` call is
  independent; "context retention" within a single answer (e.g. reusing an
  already-resolved asset across the multi-step plan for *that* question) is
  implemented, but a follow-up question like "what about the other one?"
  does not carry state from the previous turn. Adding a `conversation_id`
  and a short rolling history is the natural next step.
- **The GUI has no authentication/authorization of its own** — it assumes a
  trusted single-user local/demo deployment, matching the assignment's scope
  (a production deployment would add this at the GUI or an API gateway
  layer, not inside the copilot orchestration logic).
- **Ticket/write-operation confirmation is out of scope for this use case.**
  The submission guidelines mention "ticket or issue creation must require
  explicit confirmation," but this use case (alarm investigation + procedure
  guidance) is read-only against the Alarm Management API by design — no
  tool in `mcp-servers/alarm-management/server.py` performs a write
  operation, so there is no confirmation flow to build for this scope.

## Future improvements

- Swap the lexical retriever for an embedding-based backend (OpenAI
  embeddings or local `sentence-transformers`) behind the existing
  `Retriever` interface, with a reranking pass over the top candidates.
- Add an `LLMPlanner` for intent/entity extraction, with the heuristic
  planner retained as the zero-config fallback.
- Add a `conversation_id`-scoped short-term memory so multi-turn
  investigations ("show me its related assets" after a prior answer) work
  without repeating the full asset name.
- Expose the remaining simulator endpoints (trends, flood analysis,
  rationalization candidates, KPI definitions, on-the-fly calculation code)
  as additional MCP tools for a fuller "reliability engineering" workflow.
- Add a second MCP server (e.g. a maintenance/ticketing system) to
  demonstrate multi-server tool discovery, as the assignment allows
  ("The candidate may expose additional systems through the same MCP server
  or through a second MCP server").
