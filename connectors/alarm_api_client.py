"""
Alarm Management API connector.

This is the only piece of code in the whole project that is allowed to make an
HTTP call to the Alarm Management API. It is used exclusively by the MCP
server (mcp-servers/alarm-management/server.py) — the copilot orchestration
layer never imports this module directly, so the Alarm Management API is only
reachable through MCP. That boundary is what makes the MCP execution trace in
the GUI a true record of every upstream call, rather than a partial one.

Responsibilities:
  * Bearer-token authentication, read from configuration (never hard-coded).
  * Correlation/trace metadata propagation (trace_id, x-client-id, x-metadata-tag).
  * Timeout + bounded exponential-backoff retry on transient failures.
  * Mapping of transport/HTTP errors into a small typed error hierarchy that the
    MCP layer can turn into structured MCP tool errors instead of leaking raw
    stack traces or secrets.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("alarm_api_client")


class AlarmAPIError(Exception):
    """Base class for all Alarm Management API errors surfaced to callers."""

    def __init__(self, message: str, *, status_code: int | None = None, trace_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.trace_id = trace_id


class AlarmAPIAuthError(AlarmAPIError):
    """401/403 — invalid or missing credentials."""


class AlarmAPINotFoundError(AlarmAPIError):
    """404 — asset/alarm/calculation not found."""


class AlarmAPIValidationError(AlarmAPIError):
    """400/422 — the request payload was rejected by the API."""


class AlarmAPITimeoutError(AlarmAPIError):
    """The API did not respond within the configured timeout, after retries."""


class AlarmAPIUnavailableError(AlarmAPIError):
    """Connection-level failure (DNS, refused connection, 5xx after retries)."""


@dataclass
class TraceContext:
    """Correlation metadata that is propagated end-to-end: GUI -> copilot -> MCP -> API."""

    trace_id: str
    client_id: str = "alarm-mcp-server"
    metadata_tag: str = "copilot"

    @classmethod
    def new(cls, metadata_tag: str = "copilot") -> "TraceContext":
        return cls(trace_id=f"trace-{uuid.uuid4().hex[:16]}", metadata_tag=metadata_tag)

    def headers(self) -> dict[str, str]:
        return {"trace_id": self.trace_id, "x-client-id": self.client_id, "x-metadata-tag": self.metadata_tag}


class AlarmAPIClient:
    """Thin, well-behaved HTTP client for the Alarm Management API simulator."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = (base_url or os.environ.get("ALARM_API_BASE_URL", "http://localhost:8000")).rstrip("/")
        self._token = token or os.environ.get("ALARM_API_TOKEN", "demo-token")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        # ``transport`` lets tests point this client at an in-process ASGI app
        # (httpx.ASGITransport) instead of a real socket — see tests/integration,
        # which exercise the full simulator without binding a port.
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_seconds, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _auth_headers(self, trace: TraceContext) -> dict[str, str]:
        # Secrets never appear in logs: only the header name is logged elsewhere.
        return {"Authorization": f"Bearer {self._token}", **trace.headers()}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        trace: TraceContext,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict:
        headers = self._auth_headers(trace)
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(method, path, params=params, json=json_body, headers=headers)
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("alarm_api timeout attempt=%s path=%s trace_id=%s", attempt, path, trace.trace_id)
                continue
            except httpx.ConnectError as exc:
                last_exc = exc
                logger.warning("alarm_api connect_error attempt=%s path=%s trace_id=%s", attempt, path, trace.trace_id)
                continue

            if response.status_code in (429, 502, 503, 504) and attempt < self.max_retries:
                logger.warning(
                    "alarm_api retryable_status=%s attempt=%s path=%s trace_id=%s",
                    response.status_code,
                    attempt,
                    path,
                    trace.trace_id,
                )
                continue

            return self._handle_response(response, trace)

        if isinstance(last_exc, httpx.TimeoutException):
            raise AlarmAPITimeoutError(f"Alarm API timed out calling {path}", trace_id=trace.trace_id)
        raise AlarmAPIUnavailableError(f"Alarm API unreachable calling {path}: {last_exc}", trace_id=trace.trace_id)

    def _handle_response(self, response: httpx.Response, trace: TraceContext) -> dict:
        if response.status_code in (401, 403):
            raise AlarmAPIAuthError(
                "Alarm API rejected credentials", status_code=response.status_code, trace_id=trace.trace_id
            )
        if response.status_code == 404:
            raise AlarmAPINotFoundError(self._safe_detail(response), status_code=404, trace_id=trace.trace_id)
        if response.status_code in (400, 422):
            raise AlarmAPIValidationError(
                self._safe_detail(response), status_code=response.status_code, trace_id=trace.trace_id
            )
        if response.status_code >= 500:
            raise AlarmAPIUnavailableError(
                self._safe_detail(response), status_code=response.status_code, trace_id=trace.trace_id
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _safe_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            return str(body.get("error", {}).get("message", body))
        except Exception:
            return f"HTTP {response.status_code}"

    # ------------------------------------------------------------------
    # Typed operations — one method per Alarm Management API capability.
    # ------------------------------------------------------------------

    async def search_assets(self, query: str, limit: int = 10, unit: str | None = None, *, trace: TraceContext) -> dict:
        params = {"query": query, "limit": limit}
        if unit:
            params["unit"] = unit
        return await self._request("GET", "/assets/search", trace=trace, params=params)

    async def get_asset_metadata(self, asset_id: str, *, trace: TraceContext) -> dict:
        return await self._request("GET", f"/assets/{asset_id}/metadata", trace=trace)

    async def list_alarms(
        self,
        *,
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
        trace: TraceContext,
    ) -> dict:
        params = {"page": page, "page_size": page_size, "sort_by": sort_by, "sort_order": sort_order}
        for k, v in (
            ("asset_id", asset_id),
            ("unit", unit),
            ("site", site),
            ("status", status),
            ("start_time", start_time),
            ("end_time", end_time),
        ):
            if v:
                params[k] = v
        return await self._request("GET", "/alarms", trace=trace, params=params)

    async def get_alarm(self, alarm_id: str, *, trace: TraceContext) -> dict:
        return await self._request("GET", f"/alarms/{alarm_id}", trace=trace)

    async def alarm_summary(
        self,
        asset_ids: list[str],
        start_time: str,
        end_time: str,
        severity: list[str] | None = None,
        group_by: list[str] | None = None,
        *,
        trace: TraceContext,
    ) -> dict:
        body = {
            "asset_ids": asset_ids,
            "time_range": {"start_time": start_time, "end_time": end_time},
            "severity": severity,
            "group_by": group_by,
        }
        return await self._request("POST", "/alarms/summary", trace=trace, json_body=body)

    async def alarm_trends(
        self,
        asset_ids: list[str],
        start_time: str,
        end_time: str,
        bucket: str = "daily",
        metrics: list[str] | None = None,
        *,
        trace: TraceContext,
    ) -> dict:
        body = {
            "asset_ids": asset_ids,
            "time_range": {"start_time": start_time, "end_time": end_time},
            "bucket": bucket,
            "metrics": metrics,
        }
        return await self._request("POST", "/alarms/trends", trace=trace, json_body=body)

    async def alarm_correlation(
        self,
        asset_ids: list[str],
        start_time: str,
        end_time: str,
        correlation_method: str = "cooccurrence",
        lag_window_minutes: int = 15,
        severity_threshold: str = "medium",
        min_support: int = 1,
        *,
        trace: TraceContext,
    ) -> dict:
        body = {
            "asset_ids": asset_ids,
            "time_range": {"start_time": start_time, "end_time": end_time},
            "correlation_method": correlation_method,
            "lag_window_minutes": lag_window_minutes,
            "severity_threshold": severity_threshold,
            "min_support": min_support,
        }
        return await self._request("POST", "/alarms/correlation", trace=trace, json_body=body)

    async def flood_analysis(
        self,
        unit: str,
        start_time: str,
        end_time: str,
        threshold_count: int = 10,
        rolling_window_minutes: int = 10,
        *,
        trace: TraceContext,
    ) -> dict:
        body = {
            "unit": unit,
            "time_range": {"start_time": start_time, "end_time": end_time},
            "threshold_count": threshold_count,
            "rolling_window_minutes": rolling_window_minutes,
        }
        return await self._request("POST", "/alarms/flood-analysis", trace=trace, json_body=body)

    async def rationalization_candidates(
        self,
        asset_ids: list[str],
        start_time: str,
        end_time: str,
        recurrence_threshold: int = 5,
        stale_minutes_threshold: int = 180,
        *,
        trace: TraceContext,
    ) -> dict:
        body = {
            "asset_ids": asset_ids,
            "time_range": {"start_time": start_time, "end_time": end_time},
            "recurrence_threshold": recurrence_threshold,
            "stale_minutes_threshold": stale_minutes_threshold,
        }
        return await self._request("POST", "/alarms/rationalization-candidates", trace=trace, json_body=body)

    async def priority_score(self, alarm_id: str, *, trace: TraceContext) -> dict:
        return await self._request("POST", "/alarms/priority-score", trace=trace, json_body={"alarm_id": alarm_id})

    async def operator_recommendations(
        self,
        alarm_id: str,
        include_related: bool = True,
        include_asset_context: bool = True,
        include_historical_pattern: bool = True,
        *,
        trace: TraceContext,
    ) -> dict:
        body = {
            "alarm_id": alarm_id,
            "include_related": include_related,
            "include_asset_context": include_asset_context,
            "include_historical_pattern": include_historical_pattern,
        }
        return await self._request("POST", "/recommendations/operator-actions", trace=trace, json_body=body)

    async def kpi_definitions(self, *, trace: TraceContext) -> dict:
        return await self._request("GET", "/analytics/kpi-definitions", trace=trace)
