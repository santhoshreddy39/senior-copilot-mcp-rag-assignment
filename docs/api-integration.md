# API Integration

## Source system: Alarm Management API

`apps/backend/simulator/` is a from-scratch FastAPI implementation of the API
surface defined by the reference Postman collections in `postman/` (which
were provided as the specification, not as a server to run against). It
implements every endpoint, method, auth scheme, and trace-header contract
described there:

- `GET /health`
- `GET /assets/search`, `GET /assets/{asset_id}/metadata`
- `GET /alarms`, `GET /alarms/{alarm_id}`
- `POST /alarms/summary`, `/trends`, `/correlation`, `/flood-analysis`,
  `/rationalization-candidates`, `/priority-score`
- `POST /recommendations/operator-actions`
- `POST /calculation-code/generate`, `/calculation-code/execute`
- `GET /analytics/kpi-definitions`

Data is synthetic but deterministic (fixed random seed) and internally
consistent: assets, alarms, severities, timestamps, and recurrence patterns
are generated once at process start so responses are reproducible across
runs, and a handful of specific alarms are seeded as currently-active so the
assignment's example questions ("show active critical alarms for Boiler Feed
Pump 102...") always resolve to real data rather than depending on random
chance (`apps/backend/simulator/data.py::GUARANTEED_ACTIVE`).

## Authentication

Bearer token (`Authorization: Bearer <ALARM_API_TOKEN>`), enforced by a
FastAPI dependency (`require_auth`) on every endpoint except `/health`.
Missing or incorrect token -> `401` with a structured `{"error": {...}}`
body (never a stack trace).

## Trace / correlation metadata

A `trace_and_logging_middleware` reads `trace_id`, `x-client-id`, and
`x-metadata-tag` request headers (generating a `trace_id` if none was sent),
attaches them to `request.state`, logs a structured line for every request
(`trace_id=... client_id=... method=... path=... status=... duration_ms=...`),
and echoes `x-trace-id` / `x-client-id` back on the response so a caller can
confirm end-to-end propagation.

## Pagination

`GET /alarms` implements `page` / `page_size` (1-500) with a
`{"data": [...], "pagination": {"page", "page_size", "total_count",
"total_pages"}}` envelope; `GET /assets/search` uses a simple `limit`.

## Error mapping (connector -> MCP tool error)

`connectors/alarm_api_client.py` maps every HTTP response into a small typed
exception hierarchy:

| HTTP status | Exception | MCP tool error message |
|---|---|---|
| 401 / 403 | `AlarmAPIAuthError` | "Alarm API rejected the configured credentials. Check ALARM_API_TOKEN." |
| 404 | `AlarmAPINotFoundError` | "Not found: <detail>" |
| 400 / 422 | `AlarmAPIValidationError` | "Invalid request: <detail>" |
| timeout (after retries) | `AlarmAPITimeoutError` | "Alarm API timed out..." |
| 5xx / connection failure (after retries) | `AlarmAPIUnavailableError` | "Alarm API is currently unavailable..." |

No response body, header value, or credential is ever echoed verbatim into a
tool error — see `tests/integration/test_mcp_server_tools.py::test_not_found_is_mapped_to_tool_error_without_leaking_internals`.

## Timeout and retry behavior

Each request has a 5-second timeout (`ALARM_API_TIMEOUT_SECONDS`) and up to 2
retries (`ALARM_API_MAX_RETRIES`) on timeout, connection failure, or a
retryable status (429/502/503/504), with the retry loop living in
`AlarmAPIClient._request`.

## Testing without a live simulator process

`AlarmAPIClient` accepts an optional `transport` parameter
(`httpx.AsyncBaseTransport`), which lets unit tests point it at an in-process
ASGI transport wrapping the real FastAPI app (`httpx.ASGITransport`) instead
of a real socket — see `tests/unit/test_connectors.py` and the
`simulator_transport` fixture in `conftest.py`. Integration tests that need a
genuine TCP server (because the MCP server subprocess connects over real
HTTP) instead use the `live_simulator_url` fixture, which starts the
simulator as a subprocess on a free port.
