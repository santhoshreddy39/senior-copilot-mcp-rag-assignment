"""
Alarm Management MCP Server.

Exposes a curated slice of the Alarm Management API as MCP tools:

  * asset search, asset metadata, alarm retrieval, alarm summary/trend,
    correlation, priority scoring, and operator recommendations
  * typed input/output via Python type hints (FastMCP derives the JSON schema)
  * input validation (FastMCP + explicit range/enum checks below)
  * authentication + configuration handled entirely inside the connector,
    never exposed to the MCP client
  * timeouts + retries (connectors/alarm_api_client.py)
  * correlation/trace metadata propagated on every upstream call
  * external API errors mapped to typed MCP ToolError messages — no raw
    stack traces or secrets ever reach the MCP client
  * runnable and testable independently of the copilot (``python server.py``,
    or see tests/unit/test_mcp_server_tools.py which calls the tool functions
    directly without going through the MCP protocol at all)

Run standalone (stdio transport, the default the copilot backend uses):

    ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token \\
        python mcp-servers/alarm-management/server.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Allow running this file directly (``python server.py``) as well as importing
# it as a package module, by making the repo root importable either way.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

load_dotenv()  # no-op if .env is absent (e.g. docker-compose already injected env vars)

from connectors.alarm_api_client import (  # noqa: E402
    AlarmAPIAuthError,
    AlarmAPIClient,
    AlarmAPINotFoundError,
    AlarmAPITimeoutError,
    AlarmAPIUnavailableError,
    AlarmAPIValidationError,
    TraceContext,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
logger = logging.getLogger("alarm_mcp_server")

mcp = FastMCP(
    name="alarm-management",
    instructions=(
        "Tools for investigating industrial process alarms: resolving asset names to IDs, "
        "retrieving active/historical alarms, correlating alarms across assets, scoring alarm "
        "priority, and generating operator recommendations. Always resolve an asset name with "
        "search_assets before calling tools that require an asset_id."
    ),
)

_client: AlarmAPIClient | None = None


def get_client() -> AlarmAPIClient:
    global _client
    if _client is None:
        _client = AlarmAPIClient(
            base_url=os.environ.get("ALARM_API_BASE_URL", "http://localhost:8000"),
            token=os.environ.get("ALARM_API_TOKEN", "demo-token"),
            timeout_seconds=float(os.environ.get("ALARM_API_TIMEOUT_SECONDS", "5.0")),
            max_retries=int(os.environ.get("ALARM_API_MAX_RETRIES", "2")),
        )
    return _client


def _trace(trace_id: str | None) -> TraceContext:
    if trace_id:
        return TraceContext(trace_id=trace_id, client_id="alarm-mcp-server", metadata_tag="copilot")
    return TraceContext.new(metadata_tag="copilot")


async def _call(coro, *, tool_name: str):
    """
    Maps connector-level errors into MCP ToolError with a clear, non-leaking message. This
    is the single place where "external API errors mapped to understandable MCP errors" and
    "avoid exposing secrets in logs or responses" are enforced for every tool below.
    """
    try:
        return await coro
    except AlarmAPIAuthError as e:
        logger.error("tool=%s auth_error trace_id=%s", tool_name, e.trace_id)
        raise ToolError("Alarm API rejected the configured credentials. Check ALARM_API_TOKEN.") from e
    except AlarmAPINotFoundError as e:
        raise ToolError(f"Not found: {e.message}") from e
    except AlarmAPIValidationError as e:
        raise ToolError(f"Invalid request: {e.message}") from e
    except AlarmAPITimeoutError as e:
        logger.error("tool=%s timeout trace_id=%s", tool_name, e.trace_id)
        raise ToolError("Alarm API timed out. It may be under load; try again or narrow the request.") from e
    except AlarmAPIUnavailableError as e:
        logger.error("tool=%s unavailable trace_id=%s detail=%s", tool_name, e.trace_id, e.message)
        raise ToolError(
            "Alarm API is currently unavailable. Confirm ALARM_API_BASE_URL and that the simulator is running."
        ) from e


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_assets(
    query: str, limit: int = 10, unit: str | None = None, trace_id: str | None = None
) -> dict[str, Any]:
    """
    Resolve a free-text asset name or partial name (e.g. "Boiler Feed Pump 101",
    "compressor", "motor") to one or more asset IDs. Always call this first when
    the user refers to an asset by name — every other tool that needs an
    asset_id requires the ID returned here, not the display name.

    Args:
        query: Asset name or partial name / type / tag to search for.
        limit: Maximum number of results to return (1-100).
        unit: Optional exact unit filter, e.g. "Unit 2".
        trace_id: Optional correlation ID to propagate; a new one is generated if omitted.
    """
    if not query or not query.strip():
        raise ToolError("query must not be empty")
    if not (1 <= limit <= 100):
        raise ToolError("limit must be between 1 and 100")
    client = get_client()
    return await _call(
        client.search_assets(query, limit=limit, unit=unit, trace=_trace(trace_id)), tool_name="search_assets"
    )


@mcp.tool()
async def get_asset_metadata(asset_id: str, trace_id: str | None = None) -> dict[str, Any]:
    """
    Fetch full metadata for a resolved asset ID: type, unit, site, criticality,
    manufacturer/model, install and last-maintenance dates, and related assets
    in the same unit (useful for "what else should be inspected" questions).

    Args:
        asset_id: An asset ID as returned by search_assets (e.g. "AST-1000").
        trace_id: Optional correlation ID to propagate.
    """
    if not asset_id:
        raise ToolError("asset_id must not be empty")
    client = get_client()
    return await _call(client.get_asset_metadata(asset_id, trace=_trace(trace_id)), tool_name="get_asset_metadata")


@mcp.tool()
async def get_alarms(
    asset_id: str | None = None,
    unit: str | None = None,
    site: str | None = None,
    status: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "start_time",
    sort_order: str = "desc",
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve alarms with flexible filtering and pagination. Use asset_id for a
    single asset, or unit/site for a broader sweep (e.g. "active critical
    alarms in EastRefinery"). Timestamps are ISO-8601 UTC, e.g.
    "2026-06-01T00:00:00Z".

    Args:
        asset_id: Filter to a single asset ID.
        unit: Filter to a unit, e.g. "Unit 2".
        site: Filter to a site, e.g. "EastRefinery".
        status: One of active | acknowledged | cleared | shelved.
        start_time: ISO-8601 UTC lower bound on alarm start time.
        end_time: ISO-8601 UTC upper bound on alarm start time.
        page: 1-based page number.
        page_size: Results per page (1-500).
        sort_by: One of start_time | severity | status | asset_name.
        sort_order: asc | desc.
        trace_id: Optional correlation ID to propagate.
    """
    if status and status not in ("active", "acknowledged", "cleared", "shelved"):
        raise ToolError("status must be one of active, acknowledged, cleared, shelved")
    if sort_order not in ("asc", "desc"):
        raise ToolError("sort_order must be asc or desc")
    if not (1 <= page_size <= 500) or page < 1:
        raise ToolError("page must be >= 1 and page_size must be between 1 and 500")
    client = get_client()
    return await _call(
        client.list_alarms(
            asset_id=asset_id,
            unit=unit,
            site=site,
            status=status,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            trace=_trace(trace_id),
        ),
        tool_name="get_alarms",
    )


@mcp.tool()
async def get_alarm_by_id(alarm_id: str, trace_id: str | None = None) -> dict[str, Any]:
    """
    Fetch full detail for a single alarm, including related asset IDs and
    applicable operating-procedure document tags for RAG retrieval.

    Args:
        alarm_id: An alarm ID as returned by get_alarms (e.g. "ALM-...").
        trace_id: Optional correlation ID to propagate.
    """
    if not alarm_id:
        raise ToolError("alarm_id must not be empty")
    client = get_client()
    return await _call(client.get_alarm(alarm_id, trace=_trace(trace_id)), tool_name="get_alarm_by_id")


@mcp.tool()
async def get_alarm_summary(
    asset_ids: list[str],
    start_time: str,
    end_time: str,
    severity: list[str] | None = None,
    group_by: list[str] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Summarize alarm counts and recurrence over a time window, grouped by
    alarm_name (default), asset_id, severity, or unit. Use this to answer
    "why does X keep alarming" style questions before drilling into correlation.

    Args:
        asset_ids: One or more asset IDs to summarize.
        start_time: ISO-8601 UTC window start.
        end_time: ISO-8601 UTC window end.
        severity: Optional severity filter, e.g. ["high", "critical"].
        group_by: Optional grouping field, e.g. ["alarm_name"].
        trace_id: Optional correlation ID to propagate.
    """
    if not asset_ids:
        raise ToolError("asset_ids must contain at least one asset ID")
    client = get_client()
    return await _call(
        client.alarm_summary(
            asset_ids, start_time, end_time, severity=severity, group_by=group_by, trace=_trace(trace_id)
        ),
        tool_name="get_alarm_summary",
    )


@mcp.tool()
async def get_alarm_correlation(
    asset_ids: list[str],
    start_time: str,
    end_time: str,
    lag_window_minutes: int = 15,
    severity_threshold: str = "medium",
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Find alarms that co-occur within a short time window (possible common root
    cause) and surface related assets whose alarms overlap with the given
    asset's alarms. Use after get_alarm_summary to explain *why* an alarm is
    recurring, and to identify what else should be inspected.

    Args:
        asset_ids: One or more asset IDs to correlate.
        start_time: ISO-8601 UTC window start.
        end_time: ISO-8601 UTC window end.
        lag_window_minutes: Max minutes between two alarms to count as co-occurring.
        severity_threshold: Minimum severity to include: low | medium | high | critical.
        trace_id: Optional correlation ID to propagate.
    """
    if not asset_ids:
        raise ToolError("asset_ids must contain at least one asset ID")
    if severity_threshold not in ("low", "medium", "high", "critical"):
        raise ToolError("severity_threshold must be one of low, medium, high, critical")
    client = get_client()
    return await _call(
        client.alarm_correlation(
            asset_ids,
            start_time,
            end_time,
            lag_window_minutes=lag_window_minutes,
            severity_threshold=severity_threshold,
            trace=_trace(trace_id),
        ),
        tool_name="get_alarm_correlation",
    )


@mcp.tool()
async def get_priority_score(alarm_id: str, trace_id: str | None = None) -> dict[str, Any]:
    """
    Compute a 0-100 priority score and P1-P4 priority level for a single alarm,
    combining severity, asset criticality, recurrence, and current status. Use
    this to answer "which alarm is highest priority" questions.

    Args:
        alarm_id: An alarm ID as returned by get_alarms.
        trace_id: Optional correlation ID to propagate.
    """
    if not alarm_id:
        raise ToolError("alarm_id must not be empty")
    client = get_client()
    return await _call(client.priority_score(alarm_id, trace=_trace(trace_id)), tool_name="get_priority_score")


@mcp.tool()
async def get_operator_recommendations(alarm_id: str, trace_id: str | None = None) -> dict[str, Any]:
    """
    Get recommended immediate operator actions for an alarm, plus asset
    context, related assets to inspect, and whether this alarm is part of a
    recurring historical pattern. This is the API-side counterpart to the
    document-RAG operating procedure — the copilot compares the two.

    Args:
        alarm_id: An alarm ID as returned by get_alarms.
        trace_id: Optional correlation ID to propagate.
    """
    if not alarm_id:
        raise ToolError("alarm_id must not be empty")
    client = get_client()
    return await _call(
        client.operator_recommendations(alarm_id, trace=_trace(trace_id)), tool_name="get_operator_recommendations"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
