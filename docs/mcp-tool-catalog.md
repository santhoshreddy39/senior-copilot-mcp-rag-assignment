# MCP Tool Catalog — `alarm-management` server

Source: `mcp-servers/alarm-management/server.py`. Transport: stdio (spawned as
a subprocess by the copilot backend; also runnable standalone, see below).

**Common to every tool:**
- **Authentication behavior:** the MCP server never accepts or forwards a
  credential from the MCP client. It reads `ALARM_API_TOKEN` from its own
  process environment and attaches it as a `Bearer` token to every Alarm
  Management API call via `connectors/alarm_api_client.py`. A wrong/missing
  token surfaces as a `ToolError` ("Alarm API rejected the configured
  credentials...") — never as a raw 401 body, and the token itself is never
  included in a tool result or a log line.
- **Timeout behavior:** each upstream HTTP call has a 5s timeout by default
  (`ALARM_API_TIMEOUT_SECONDS`), after which the client retries transient
  failures up to `ALARM_API_MAX_RETRIES` (default 2) times with a fresh
  attempt, then raises `AlarmAPITimeoutError`, mapped to a `ToolError`.
- **Trace metadata:** every tool accepts an optional `trace_id`. If omitted, a
  new one is generated (`trace-<random>`). It is sent to the Alarm Management
  API as the `trace_id` header alongside `x-client-id: alarm-mcp-server` and
  `x-metadata-tag: copilot`, and the simulator echoes it back as
  `x-trace-id` — the same ID appears in both the MCP server's and the
  simulator's structured logs for a given call, and in the MCP execution
  trace the GUI renders.
- **Error behavior:** all Alarm Management API failures (401/403, 404,
  400/422, 5xx, timeout, connection failure) are mapped from the connector's
  typed exception hierarchy (`connectors/alarm_api_client.py`) into a single
  `mcp.server.fastmcp.exceptions.ToolError` with a clear, non-leaking message.

Standalone run command:

```bash
ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token \
    python mcp-servers/alarm-management/server.py
```

---

## `search_assets`

**Purpose:** Resolve a free-text asset name/partial name/type to one or more
asset IDs. Always the first tool called when a question names an asset.

**Underlying operation:** `GET /assets/search`

**Input schema:**
```json
{
  "query": "string (required)",
  "limit": "integer, default 10",
  "unit": "string | null",
  "trace_id": "string | null"
}
```

**Output:** `{"results": [{"asset_id", "name", "asset_type", "unit", "site", "criticality"}], "count", "query"}`

**Example invocation:**
```json
{"query": "Boiler Feed Pump 101"}
```

**Example response:**
```json
{"results": [{"asset_id": "AST-1000", "name": "Boiler Feed Pump 101",
  "asset_type": "Centrifugal Pump", "unit": "Unit 3", "site": "EastRefinery",
  "criticality": "high"}], "count": 1, "query": "Boiler Feed Pump 101"}
```

---

## `get_asset_metadata`

**Purpose:** Full metadata for a resolved asset: type, unit, site,
criticality, manufacturer/model, install/maintenance dates, and related
assets in the same unit.

**Underlying operation:** `GET /assets/{asset_id}/metadata`

**Input schema:** `{"asset_id": "string (required)", "trace_id": "string | null"}`

**Error behavior (tool-specific):** unknown `asset_id` -> `ToolError("Not found: Unknown asset_id: ...")`.

**Example invocation:** `{"asset_id": "AST-1000"}`

---

## `get_alarms`

**Purpose:** Flexible, paginated alarm retrieval by asset, unit, site,
status, and/or time window — the main tool for "show active/critical alarms"
questions.

**Underlying operation:** `GET /alarms`

**Input schema:**
```json
{
  "asset_id": "string | null", "unit": "string | null", "site": "string | null",
  "status": "active|acknowledged|cleared|shelved | null",
  "start_time": "ISO-8601 UTC | null", "end_time": "ISO-8601 UTC | null",
  "page": "integer, default 1", "page_size": "integer 1-500, default 50",
  "sort_by": "start_time|severity|status|asset_name, default start_time",
  "sort_order": "asc|desc, default desc", "trace_id": "string | null"
}
```

**Input validation (tool-specific):** rejects an unknown `status` or
`sort_order`, or `page_size` outside 1-500, with a `ToolError` before any
network call is made.

**Output:** `{"data": [alarm...], "pagination": {"page", "page_size", "total_count", "total_pages"}}`

**Example invocation:** `{"asset_id": "AST-1001", "status": "active", "page_size": 10}`

---

## `get_alarm_by_id`

**Purpose:** Full detail for one alarm, including related asset IDs and
applicable document tags for RAG retrieval.

**Underlying operation:** `GET /alarms/{alarm_id}`

**Input schema:** `{"alarm_id": "string (required)", "trace_id": "string | null"}`

---

## `get_alarm_summary`

**Purpose:** Grouped alarm counts and recurrence stats over a time window —
answers "why does X keep alarming".

**Underlying operation:** `POST /alarms/summary`

**Input schema:**
```json
{
  "asset_ids": ["string", "..."], "start_time": "ISO-8601 UTC (required)",
  "end_time": "ISO-8601 UTC (required)", "severity": ["string"] , "group_by": ["string"],
  "trace_id": "string | null"
}
```

**Input validation:** `asset_ids` must be non-empty.

**Example invocation:**
```json
{"asset_ids": ["AST-1000"], "start_time": "2026-06-24T00:00:00Z",
 "end_time": "2026-09-22T00:00:00Z", "severity": ["high", "critical"]}
```

---

## `get_alarm_correlation`

**Purpose:** Finds alarms that co-occur within a short lag window (possible
common root cause) and related assets whose alarms overlap — the "advanced
operation" required by the assignment brief.

**Underlying operation:** `POST /alarms/correlation`

**Input schema:**
```json
{
  "asset_ids": ["string"], "start_time": "ISO-8601 UTC (required)",
  "end_time": "ISO-8601 UTC (required)", "lag_window_minutes": "integer, default 15",
  "severity_threshold": "low|medium|high|critical, default medium",
  "trace_id": "string | null"
}
```

**Output:** `{"correlated_pairs": [{"alarm_name_a", "alarm_name_b", "cooccurrence_count", "avg_lag_minutes", "confidence"}], "related_assets": [...]}`

---

## `get_priority_score`

**Purpose:** 0-100 priority score and P1-P4 level for one alarm, combining
severity, asset criticality, recurrence, and current status.

**Underlying operation:** `POST /alarms/priority-score`

**Input schema:** `{"alarm_id": "string (required)", "trace_id": "string | null"}`

**Example response:**
```json
{"alarm_id": "ALM-...", "priority_score": 81, "priority_level": "P1",
 "factors": {"severity_score": 40, "asset_criticality_score": 15, "recurrence_score": 6,
             "status_score": 20, "recurrence_count_90d": 3}}
```

---

## `get_operator_recommendations`

**Purpose:** Recommended immediate operator actions, asset context, related
assets to inspect, and historical-pattern flag for an alarm — the API-side
counterpart the copilot compares against the RAG-retrieved procedure.

**Underlying operation:** `POST /recommendations/operator-actions`

**Input schema:** `{"alarm_id": "string (required)", "trace_id": "string | null"}`

---

## Not exposed through MCP (by design)

`/alarms/trends`, `/alarms/flood-analysis`, `/alarms/rationalization-candidates`,
`/calculation-code/*`, and `/analytics/kpi-definitions` exist in the simulator
(matching the Postman reference contract in full) but are not exposed as MCP
tools. The assignment asks for "asset search, alarm retrieval, alarm summary
or trend analysis, [and] one advanced operation" as the minimum tool surface;
the eight tools above cover that with margin (summary, correlation, *and*
priority scoring/recommendations as advanced operations) while keeping the
tool list small enough for reliable LLM tool selection. Adding the remaining
endpoints as tools is a natural, low-risk extension — see
`docs/known-limitations.md`.
