# Architecture

## Component overview

```
┌──────────────────┐
│  Streamlit GUI    │  apps/frontend/app.py
│  (chat, trace,    │  - talks ONLY to the copilot backend's HTTP API
│  citations panel) │
└─────────┬─────────┘
          │ HTTP (/chat, /mcp/tools, /health)
          ▼
┌──────────────────────────────────────────────────────────────────┐
│  Copilot backend (apps/backend/main.py)                          │
│  "copilot orchestration layer"                                    │
│                                                                    │
│  ┌────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
│  │  NLU        │──▶│  Orchestrator     │──▶│  LLM provider       │  │
│  │  (intent +  │   │  (multi-step MCP  │   │  (pluggable:        │  │
│  │  entities)  │   │  + RAG planning)  │   │  OpenAI/Anthropic/  │  │
│  └────────────┘   └─────────┬────────┘   │  Azure/Template)     │  │
│                              │            └────────────────────┘  │
│                    ┌─────────┴─────────┐                          │
│                    ▼                   ▼                          │
│           ┌────────────────┐  ┌──────────────────┐                │
│           │  MCP client     │  │  RAG retriever    │                │
│           │  (stdio)        │  │  (hybrid TF-IDF   │                │
│           └────────┬────────┘  │   + BM25)         │                │
│                     │           └─────────┬────────┘                │
└─────────────────────┼─────────────────────┼─────────────────────┘
                       │ MCP protocol        │ reads
                       │ (subprocess, stdio) │
                       ▼                     ▼
          ┌─────────────────────┐   ┌──────────────────────┐
          │  Alarm Management    │   │  rag/documents/*.md   │
          │  MCP server           │   │  (operating procs,    │
          │  (mcp-servers/         │   │  maintenance manuals, │
          │  alarm-management)     │   │  troubleshooting,     │
          └──────────┬────────────┘   │  safety instructions) │
                     │ HTTP (Bearer)   └──────────────────────┘
                     │ + trace headers
                     ▼
          ┌─────────────────────┐
          │  Alarm Management     │
          │  API simulator          │  apps/backend/simulator/
          │  (FastAPI)               │  — implements the Postman
          └─────────────────────┘     reference collection contract
```

## Request flow, end to end

1. The GUI sends the user's natural-language question to `POST /chat` on the
   copilot backend.
2. `apps/backend/copilot/nlu.py` classifies intent (active alarms / recurring
   investigation / highest priority / related assets / procedure lookup /
   recommendation consistency / full investigation) and extracts entities
   (asset name, unit, site, severity, status, time window) with a
   deterministic rule set — see `docs/design-decisions.md` for why this is
   not an LLM call.
3. `apps/backend/copilot/orchestrator.py` plans and executes a sequence of
   MCP tool calls appropriate to the detected intent — e.g. resolve asset ->
   fetch alarms -> summarize -> correlate -> score priority -> get operator
   recommendations. Every call goes through `apps/backend/mcp_client/client.py`,
   which owns a single MCP session over the **stdio transport** to the
   candidate-developed MCP server (spawned as a subprocess).
4. The MCP server (`mcp-servers/alarm-management/server.py`) validates the
   tool arguments, calls `connectors/alarm_api_client.py` (the only code
   allowed to speak HTTP to the Alarm Management API), and maps any failure
   into a typed `ToolError`.
5. In parallel with (and informed by) the API findings, the orchestrator
   queries `rag/retrieval/retriever.py` for relevant document passages,
   filtered by the resolved asset name and scored with a low-confidence
   cutoff.
6. `apps/backend/copilot/synthesis.py` (offline template) or
   `apps/backend/llm/provider.py` (a configured LLM) combines the structured
   findings and the cited document excerpts into one grounded answer.
7. The full response — answer, structured findings, MCP execution trace, and
   RAG citations — is returned to the GUI, which renders the alarm summary
   panel, recommendations, citations, and an expandable MCP trace with raw
   request/response inspection.

## Why MCP over stdio, not a network transport

The MCP server is spawned as a subprocess and communicates with the copilot
backend over stdio — the same integration pattern used by Claude Desktop and
other MCP hosts for local servers. This was a deliberate choice over an
HTTP/SSE MCP transport:

- It keeps the MCP boundary *real* (a genuine MCP client/server exchange,
  full tool discovery and JSON-RPC framing) without adding network transport
  complexity that this assignment's scope doesn't need.
- The MCP server is still fully independently runnable and testable — see
  `make mcp-server-standalone` and `docs/mcp-tool-catalog.md` — it just also
  happens to be started by the backend process for convenience in the
  docker-compose topology.
- It reflects how the assignment is actually evaluated: "copilot bypasses
  MCP" is the red flag being tested for, not "MCP runs over HTTP".

## Layered boundaries (explicit separation of concerns)

| Layer | Code | Responsibility |
|---|---|---|
| GUI | `apps/frontend/` | Presentation only; no business logic, no direct API/MCP/RAG access |
| Copilot orchestration | `apps/backend/copilot/` | Intent detection, planning, multi-step orchestration, answer synthesis |
| MCP client / tool registry | `apps/backend/mcp_client/` | Owns the MCP session; tool discovery, invocation, error/partial-failure handling, trace capture |
| MCP server (candidate-developed) | `mcp-servers/alarm-management/` | Tool contracts, input validation, error mapping |
| API / source-system connector | `connectors/` | The *only* HTTP client for the Alarm Management API; auth, retries, timeouts, trace propagation |
| RAG ingestion pipeline | `rag/ingestion/` | Text extraction, chunking, metadata capture, prompt-injection stripping/flagging |
| RAG retrieval service | `rag/retrieval/` | Hybrid lexical index, filtering, low-confidence handling, citations |
| Domain models | `apps/backend/simulator/data.py`, `rag/ingestion/loader.py` (`Chunk`) | Typed dataclasses shared across layers |
| Authentication & configuration | `apps/backend/config.py`, `connectors/alarm_api_client.py` | Environment-driven, no secret defaults |
| Observability | structured logging in every layer + MCP execution trace surfaced to the GUI | Request ID / trace ID / tool / duration / outcome |
| Persistence | `rag/index/retrieval_index.pkl` (rebuilt by `scripts/ingest_documents.py`) | The only persisted artifact; everything else is in-memory/generated |

## Replaceable LLM provider

`apps/backend/llm/provider.py` defines an `LLMProvider` protocol with one
method (`complete`). Four implementations exist (OpenAI, Anthropic, Azure
OpenAI, and an offline `TemplateProvider`), selected purely by the
`LLM_PROVIDER` environment variable — the orchestrator never imports a vendor
SDK directly. See `docs/design-decisions.md` for why `TemplateProvider` is the
default.
