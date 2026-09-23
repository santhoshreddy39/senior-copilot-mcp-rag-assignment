# Alarm Investigation and Procedure Guidance Copilot

A copilot that investigates industrial process alarms by combining live
Alarm Management API data (via a candidate-developed MCP server) with
document-grounded guidance (via RAG over operating procedures, maintenance
manuals, troubleshooting guides, and safety instructions) — built for the
Senior Software Engineer – Copilot Integration assignment.

**Selected use case:** Alarm Investigation and Procedure Guidance Copilot
(the assigned use case per `Assignment_Use_Case.md`).

## Main capabilities

- Natural-language alarm investigation: active alarms, recurring-alarm root
  cause analysis, priority ranking, related-asset inspection, applicable
  procedure lookup, and API-vs-procedure consistency checks.
- A real MCP server (`mcp-servers/alarm-management`) exposing 8 typed tools
  over the Alarm Management API, with input validation, auth, retries,
  timeouts, trace propagation, and mapped errors.
- A real MCP client that discovers and chains those tools, driven by a
  deterministic intent/entity planner (not a lookup table — see
  `docs/design-decisions.md`).
- Document RAG (hybrid TF-IDF + BM25 retrieval, no external model download)
  with citations, low-confidence handling, and prompt-injection protection —
  see `docs/rag-design.md`.
- One combined workflow: every investigation resolves an asset through MCP,
  chains multiple Alarm Management API calls, retrieves grounding documents,
  and returns one answer with citations and a full MCP execution trace.
- A Streamlit GUI: chat, alarm summary panel, recommendations, document
  citations, an expandable MCP execution trace with raw request/response
  inspection, and loading/error/empty states.
- 76 automated tests (unit, MCP server/client, RAG, orchestration,
  end-to-end) — see [Test commands](#test-commands).

## Technology stack

Python 3.11 · FastAPI (Alarm Management API simulator + copilot backend) ·
the official `mcp` Python SDK (MCP server + client, stdio transport) ·
Streamlit (GUI) · scikit-learn + rank-bm25 (hybrid RAG retrieval, no model
download) · httpx (all HTTP) · pytest (tests) · Docker Compose (packaging).
LLM provider is pluggable and **optional** (OpenAI / Anthropic / Azure
OpenAI / an offline deterministic template — see below).

## MCP server

`mcp-servers/alarm-management/server.py` — 8 tools: `search_assets`,
`get_asset_metadata`, `get_alarms`, `get_alarm_by_id`, `get_alarm_summary`,
`get_alarm_correlation`, `get_priority_score`, `get_operator_recommendations`.
Full contract for each (input/output schema, auth, error, timeout behavior,
example invocation/response) is in **`docs/mcp-tool-catalog.md`**.

Start it independently of the copilot backend:
```bash
ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token \
    python mcp-servers/alarm-management/server.py
```

## RAG corpus and ingestion approach

`rag/documents/*.md` — 6 documents (operating procedure, troubleshooting
guide, maintenance manual, safety instruction, alarm philosophy, ticket
notes) covering the assigned use case's assets. Ingestion: heading-aware
chunking with metadata capture and prompt-injection stripping/flagging,
retrieval: hybrid TF-IDF + BM25 (no embeddings, no external calls — see
**`docs/rag-design.md`** for the full design and rationale).

```bash
python scripts/ingest_documents.py
```

## Quick start

### Option A — Docker Compose (recommended)

```bash
cp .env.example .env      # defaults work as-is; add an LLM key only if you want one
docker compose up --build
```

- GUI: http://localhost:8501
- Copilot backend: http://localhost:8100 (`/health`, `/mcp/tools`, `/chat`)
- Alarm Management API simulator: http://localhost:8000

> This exact build was validated outside Docker (every service's command run
> directly with the pinned dependency versions) but not inside an actual
> container in the sandbox this was built in — see
> `docs/known-limitations.md`. Please run `docker compose up --build` once
> yourself before submitting to confirm.

### Option B — local processes (three terminals)

```bash
make setup   # creates .venv, installs requirements-dev.txt
make ingest  # builds the RAG index
make simulator   # terminal 1 — Alarm Management API on :8000
make backend     # terminal 2 — copilot backend on :8100
make frontend    # terminal 3 — Streamlit GUI on :8501
```

## Configuration

All configuration is environment-driven — see `.env.example`. Nothing has a
real secret as a default. With `LLM_PROVIDER` unset, the copilot runs fully
offline using a deterministic template synthesizer for the final answer
(still fully grounded in real MCP + RAG data — only the prose style differs
from an LLM-written answer). Set `LLM_PROVIDER=openai|anthropic|azure_openai`
plus the matching key to use a real model instead (`requirements-llm.txt`
has the optional SDKs).

## Build and run commands

| Command | What it does |
|---|---|
| `docker compose up --build` | Full stack (simulator + backend + GUI) |
| `make simulator` / `make backend` / `make frontend` | Run one service locally |
| `make mcp-server-standalone` | Run the MCP server on its own |
| `make ingest` | Rebuild the RAG retrieval index |

## Test commands

```bash
make test               # everything (76 tests)
make test-unit          # fast, no network (40 tests)
make test-integration   # real MCP server subprocess + simulator subprocess (32 tests)
make test-e2e           # full FastAPI app through its real startup lifecycle (4 tests)
make coverage           # coverage report (83% overall at last run)
make lint               # ruff check + format --check
```

Test layout:
- `tests/unit/` — connector error mapping, NLU, simulator business logic (no network)
- `rag/tests/` — ingestion (chunking, metadata, injection stripping/flagging) and retrieval (relevance, filtering, low-confidence)
- `tests/integration/` — simulator HTTP surface; MCP server tool tests; **real** MCP client ↔ server over stdio; orchestration (multi-step MCP + RAG combined)
- `tests/e2e/` — the mandatory end-to-end scenario through the actual FastAPI app, plus a degraded/failure scenario

## Sample interactions

```
> Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.
> Why are compressor discharge pressure alarms repeatedly occurring?
> Which alarm has the highest priority in EastRefinery, and why?
> What related assets should be inspected for this motor trip alarm?
> Which operating procedure applies to this alarm?
> Are the API recommendations consistent with the maintenance manual?
> Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days,
  identify likely contributing factors, retrieve the relevant operating procedure, and
  provide recommended actions with source evidence.     <- mandatory acceptance scenario
```
Each of these is exercised by an automated test in `tests/integration/test_orchestrator_workflow.py`
and/or `tests/e2e/test_end_to_end_scenario.py`.

## Architecture summary

GUI → copilot orchestration (intent/entity planning → multi-step MCP tool
chaining + RAG retrieval → grounded answer synthesis) → MCP client (stdio) →
candidate-developed MCP server → Alarm API connector → Alarm Management API
simulator. RAG retrieval runs alongside, reading `rag/documents/`. Full
diagram and request-flow walkthrough: **`docs/architecture.md`** /
`docs/architecture-diagram.png`.

## Assumptions

- The Postman collections in `postman/` are the authoritative API contract;
  no example response bodies were provided, so response shapes were designed
  to satisfy every field referenced by the collections' own test scripts
  (e.g. `body.results[0].asset_id`, `body.data[0].alarm_id`,
  `body.calculation_id`, `body.flood_windows[0].start/.end`).
- "Senior Software Engineer – Copilot Integration" (the title in
  `Assignment_Use_Case.md`) and "AI Architect" (the role this was requested
  for) are treated as the same assignment package.
- A single-user, local/demo deployment is assumed (no GUI-level auth) per
  the assignment's scope.

## Known limitations

See **`docs/known-limitations.md`** for the full list (heuristic vs.
LLM-based planning, lexical vs. embedding retrieval, no cross-turn
conversation memory, Docker build not executed inside this sandbox, etc.)
and the corresponding future-improvements list.

## Repository structure

```
.
├── README.md
├── docs/                    architecture, MCP tool catalog, RAG design, API integration,
│                             design decisions, known limitations, architecture diagram
├── apps/
│   ├── backend/              copilot orchestration (main.py), NLU, LLM providers,
│   │                         MCP client, and the Alarm Management API simulator
│   └── frontend/              Streamlit GUI
├── mcp-servers/
│   └── alarm-management/      candidate-developed MCP server
├── rag/                      ingestion, retrieval, document corpus, RAG-specific tests
├── connectors/                 Alarm Management API HTTP client
├── tests/                    unit / integration / e2e test suites
├── postman/                  reference API contract (provided)
├── scripts/                  ingestion CLI, architecture diagram generator
├── .github/workflows/ci.yml  lint, unit/integration/e2e tests, coverage, build validation
├── .env.example, Dockerfile, docker-compose.yml, Makefile, LICENSE
```

## Demo video

_Add the link here after recording (see `Submission_and_Evaluation_Guidelines.md` §18 for what to cover)._
