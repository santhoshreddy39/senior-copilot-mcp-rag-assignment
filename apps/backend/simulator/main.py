"""
Alarm Management API Simulator.

A self-contained FastAPI backend implementing the API surface defined by the
reference Postman collections in ``postman/``: asset search, asset metadata,
alarm retrieval, alarm summaries/trends/correlation/flood-analysis/
rationalization, priority scoring, operator recommendations, on-the-fly
calculation code generation/execution, and KPI definitions.

Auth: Bearer token (see ALARM_API_TOKEN). Trace propagation: ``trace_id``,
``x-client-id`` and ``x-metadata-tag`` headers are read (or generated) on every
request and echoed back on the response so callers (the MCP server) can
correlate a request end-to-end.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

load_dotenv()  # no-op if .env is absent (e.g. docker-compose already injected env vars)

from . import analytics  # noqa: E402
from . import data as D  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("alarm_api_simulator")

API_TOKEN = os.environ.get("ALARM_API_TOKEN", "demo-token")

app = FastAPI(title="Alarm Management API Simulator", version="1.0.0")


# ---------------------------------------------------------------------------
# Cross-cutting: auth + trace propagation + structured request logging
# ---------------------------------------------------------------------------


async def require_auth(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return token


@app.middleware("http")
async def trace_and_logging_middleware(request: Request, call_next):
    start = time.time()
    trace_id = request.headers.get("trace_id") or f"trace-{uuid.uuid4().hex[:12]}"
    client_id = request.headers.get("x-client-id") or "unknown-client"
    metadata_tag = request.headers.get("x-metadata-tag") or ""

    request.state.trace_id = trace_id
    request.state.client_id = client_id

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error trace_id=%s path=%s", trace_id, request.url.path)
        raise
    duration_ms = round((time.time() - start) * 1000, 2)

    response.headers["x-trace-id"] = trace_id
    response.headers["x-client-id"] = client_id
    logger.info(
        "trace_id=%s client_id=%s method=%s path=%s status=%s duration_ms=%s metadata_tag=%s",
        trace_id,
        client_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        metadata_tag,
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": exc.detail, "status_code": exc.status_code, "trace_id": trace_id}},
    )


def _require_asset(asset_id: str) -> D.Asset:
    asset = D.ASSETS_BY_ID.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Unknown asset_id: {asset_id}")
    return asset


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid ISO-8601 timestamp: {value}")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": D._iso(datetime.now(timezone.utc)),
        "asset_count": len(D.ASSETS),
        "alarm_count": len(D.ALARMS),
    }


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@app.get("/assets/search")
async def search_assets(
    query: str = Query(...),
    limit: int = Query(10, ge=1, le=100),
    unit: str | None = None,
    _auth: str = Depends(require_auth),
):
    q = query.lower().strip()
    results = [a for a in D.ASSETS if q in a.name.lower() or q in a.asset_type.lower() or any(q in t for t in a.tags)]
    if unit:
        results = [a for a in results if a.unit == unit]
    results = results[:limit]
    return {
        "results": [
            {
                "asset_id": a.asset_id,
                "name": a.name,
                "asset_type": a.asset_type,
                "unit": a.unit,
                "site": a.site,
                "criticality": a.criticality,
            }
            for a in results
        ],
        "count": len(results),
        "query": query,
    }


@app.get("/assets/{asset_id}/metadata")
async def asset_metadata(asset_id: str, _auth: str = Depends(require_auth)):
    asset = _require_asset(asset_id)
    return {
        "asset_id": asset.asset_id,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "unit": asset.unit,
        "site": asset.site,
        "criticality": asset.criticality,
        "manufacturer": asset.manufacturer,
        "model": asset.model,
        "install_date": asset.install_date,
        "last_maintenance_date": asset.last_maintenance_date,
        "location": asset.location,
        "tags": asset.tags,
        "related_assets": [
            {"asset_id": rid, "name": D.ASSETS_BY_ID[rid].name, "relationship": "same-unit"}
            for rid in asset.related_asset_ids
            if rid in D.ASSETS_BY_ID
        ],
    }


# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------


@app.get("/alarms")
async def list_alarms(
    asset_id: str | None = None,
    unit: str | None = None,
    site: str | None = None,
    status: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = "start_time",
    sort_order: str = "desc",
    _auth: str = Depends(require_auth),
):
    rows = D.ALARMS
    if asset_id:
        rows = [a for a in rows if a["asset_id"] == asset_id]
    if unit:
        rows = [a for a in rows if a["unit"] == unit]
    if site:
        rows = [a for a in rows if a["site"] == site]
    if status:
        rows = [a for a in rows if a["status"] == status]
    if start_time:
        st = _parse_iso(start_time)
        rows = [
            a
            for a in rows
            if datetime.strptime(a["start_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= st
        ]
    if end_time:
        et = _parse_iso(end_time)
        rows = [
            a
            for a in rows
            if datetime.strptime(a["start_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= et
        ]

    reverse = sort_order == "desc"
    if sort_by in ("start_time", "severity", "status", "asset_name"):
        rows = sorted(rows, key=lambda a: a[sort_by], reverse=reverse)

    total_count = len(rows)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    start_idx = (page - 1) * page_size
    page_rows = rows[start_idx : start_idx + page_size]

    return {
        "data": page_rows,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
        },
    }


@app.get("/alarms/{alarm_id}")
async def get_alarm(alarm_id: str, _auth: str = Depends(require_auth)):
    alarm = D.ALARMS_BY_ID.get(alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail=f"Unknown alarm_id: {alarm_id}")
    asset = D.ASSETS_BY_ID.get(alarm["asset_id"])
    return {
        **alarm,
        "related_asset_ids": asset.related_asset_ids if asset else [],
    }


# ---------------------------------------------------------------------------
# Derived analytics endpoints
# ---------------------------------------------------------------------------

from .schemas import (  # noqa: E402
    AlarmCorrelationRequest,
    AlarmSummaryRequest,
    AlarmTrendsRequest,
    CalculationExecuteRequest,
    CalculationGenerateRequest,
    FloodAnalysisRequest,
    OperatorRecommendationsRequest,
    PriorityScoreRequest,
    RationalizationRequest,
)


@app.post("/alarms/summary")
async def alarms_summary(body: AlarmSummaryRequest, _auth: str = Depends(require_auth)):
    start, end = _parse_iso(body.time_range.start_time), _parse_iso(body.time_range.end_time)
    return analytics.summarize(body.asset_ids, start, end, body.severity, body.group_by)


@app.post("/alarms/trends")
async def alarms_trends(body: AlarmTrendsRequest, _auth: str = Depends(require_auth)):
    start, end = _parse_iso(body.time_range.start_time), _parse_iso(body.time_range.end_time)
    return analytics.trends(body.asset_ids, start, end, body.bucket, body.metrics)


@app.post("/alarms/correlation")
async def alarms_correlation(body: AlarmCorrelationRequest, _auth: str = Depends(require_auth)):
    start, end = _parse_iso(body.time_range.start_time), _parse_iso(body.time_range.end_time)
    return analytics.correlate(
        body.asset_ids,
        start,
        end,
        body.correlation_method,
        body.lag_window_minutes,
        body.severity_threshold,
        body.min_support,
    )


@app.post("/alarms/flood-analysis")
async def alarms_flood_analysis(body: FloodAnalysisRequest, _auth: str = Depends(require_auth)):
    start, end = _parse_iso(body.time_range.start_time), _parse_iso(body.time_range.end_time)
    return analytics.flood_analysis(body.unit, start, end, body.threshold_count, body.rolling_window_minutes)


@app.post("/alarms/rationalization-candidates")
async def alarms_rationalization_candidates(body: RationalizationRequest, _auth: str = Depends(require_auth)):
    start, end = _parse_iso(body.time_range.start_time), _parse_iso(body.time_range.end_time)
    return analytics.rationalization_candidates(
        body.asset_ids, start, end, body.recurrence_threshold, body.stale_minutes_threshold
    )


@app.post("/alarms/priority-score")
async def alarms_priority_score(body: PriorityScoreRequest, _auth: str = Depends(require_auth)):
    result = analytics.priority_score(body.alarm_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown alarm_id: {body.alarm_id}")
    return result


@app.post("/recommendations/operator-actions")
async def recommendations_operator_actions(body: OperatorRecommendationsRequest, _auth: str = Depends(require_auth)):
    result = analytics.operator_recommendations(
        body.alarm_id, body.include_related, body.include_asset_context, body.include_historical_pattern
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown alarm_id: {body.alarm_id}")
    return result


@app.post("/calculation-code/generate")
async def calculation_code_generate(body: CalculationGenerateRequest, _auth: str = Depends(require_auth)):
    return analytics.generate_calculation(body.calculation_type, body.filters)


@app.post("/calculation-code/execute")
async def calculation_code_execute(body: CalculationExecuteRequest, _auth: str = Depends(require_auth)):
    result = analytics.execute_calculation(body.calculation_id, body.filters)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown calculation_id: {body.calculation_id}")
    return result


@app.get("/analytics/kpi-definitions")
async def kpi_definitions(_auth: str = Depends(require_auth)):
    return {"kpis": analytics.KPI_DEFINITIONS}
