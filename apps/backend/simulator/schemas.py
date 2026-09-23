"""Pydantic request schemas for the Alarm Management API simulator."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TimeRange(BaseModel):
    start_time: str
    end_time: str


class AlarmSummaryRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange
    severity: list[str] | None = None
    group_by: list[str] | None = None
    kpis: list[str] | None = None


class AlarmTrendsRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange
    bucket: str = "daily"
    metrics: list[str] | None = None


class AlarmCorrelationRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange
    correlation_method: str = "cooccurrence"
    lag_window_minutes: int = 15
    severity_threshold: str = "medium"
    min_support: int = 1


class FloodAnalysisRequest(BaseModel):
    unit: str
    time_range: TimeRange
    threshold_count: int = 10
    rolling_window_minutes: int = 10


class RationalizationRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange
    recurrence_threshold: int = 5
    stale_minutes_threshold: int = 180


class PriorityScoreRequest(BaseModel):
    alarm_id: str


class OperatorRecommendationsRequest(BaseModel):
    alarm_id: str
    include_related: bool = True
    include_asset_context: bool = True
    include_historical_pattern: bool = True


class CalculationGenerateRequest(BaseModel):
    calculation_type: str
    filters: dict = Field(default_factory=dict)


class CalculationExecuteRequest(BaseModel):
    calculation_id: str
    filters: dict = Field(default_factory=dict)
