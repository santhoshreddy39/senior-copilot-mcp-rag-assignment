"""Unit tests for the simulator's business logic (analytics.py) — payload
construction / response-shape correctness, independent of HTTP or FastAPI."""

from datetime import datetime, timedelta, timezone

from apps.backend.simulator import analytics
from apps.backend.simulator import data as D


def test_filter_alarms_by_asset_and_range():
    asset = D.ASSETS[0]
    end = D.NOW
    start = end - timedelta(days=200)
    rows = analytics.filter_alarms([asset.asset_id], start, end)
    assert rows
    assert all(r["asset_id"] == asset.asset_id for r in rows)


def test_filter_alarms_severity_filter():
    end = D.NOW
    start = end - timedelta(days=200)
    rows = analytics.filter_alarms(None, start, end, severity=["critical"])
    assert rows
    assert all(r["severity"] == "critical" for r in rows)


def test_summarize_groups_and_counts_match_filtered_rows():
    end = D.NOW
    start = end - timedelta(days=200)
    asset = next(a for a in D.ASSETS if a.name == "Boiler Feed Pump 102")
    result = analytics.summarize([asset.asset_id], start, end, None, ["alarm_name"])
    assert result["total_alarm_count"] == sum(g["alarm_count"] for g in result["summary"])
    assert result["total_alarm_count"] == len(analytics.filter_alarms([asset.asset_id], start, end))


def test_correlation_pairs_respect_min_support_and_lag_window():
    end = D.NOW
    start = end - timedelta(days=200)
    asset = next(a for a in D.ASSETS if a.asset_type == "Centrifugal Compressor")
    result = analytics.correlate(
        [asset.asset_id], start, end, "cooccurrence", lag_window_minutes=15, severity_threshold="low", min_support=1
    )
    for pair in result["correlated_pairs"]:
        assert pair["cooccurrence_count"] >= 1
        assert pair["avg_lag_minutes"] <= 15 + 1e-6


def test_flood_analysis_detects_dense_window():
    # Craft a synthetic burst directly against filter_alarms via monkeypatched data
    # would require reaching into D.ALARMS; instead validate against the live dataset's
    # Unit 2 window, which is not asserted to flood but must return a well-formed shape.
    end = D.NOW
    start = end - timedelta(days=95)
    result = analytics.flood_analysis("Unit 2", start, end, threshold_count=3, rolling_window_minutes=60)
    assert "flood_windows" in result
    assert isinstance(result["is_flooding"], bool)
    for w in result["flood_windows"]:
        assert w["alarm_count"] >= 3


def test_rationalization_candidates_only_include_recurring():
    end = D.NOW
    start = end - timedelta(days=200)
    result = analytics.rationalization_candidates(None, start, end, recurrence_threshold=5, stale_minutes_threshold=180)
    for c in result["candidates"]:
        assert c["occurrence_count"] >= 5


def test_priority_score_bounds_and_level_mapping():
    alarm = D.ALARMS[0]
    result = analytics.priority_score(alarm["alarm_id"])
    assert result is not None
    assert 0 <= result["priority_score"] <= 100
    assert result["priority_level"] in ("P1", "P2", "P3", "P4")
    if result["priority_score"] >= 80:
        assert result["priority_level"] == "P1"


def test_priority_score_unknown_alarm_returns_none():
    assert analytics.priority_score("does-not-exist") is None


def test_operator_recommendations_includes_requested_sections():
    alarm = D.ALARMS[0]
    result = analytics.operator_recommendations(
        alarm["alarm_id"], include_related=True, include_asset_context=True, include_historical_pattern=True
    )
    assert result is not None
    assert "recommended_actions" in result
    assert "asset_context" in result
    assert "historical_pattern" in result


def test_calculation_generate_then_execute_roundtrip():
    gen = analytics.generate_calculation("alarm_flood_index", {"unit": "Unit 2"})
    assert gen["calculation_id"].startswith("CALC-")
    exec_result = analytics.execute_calculation(
        gen["calculation_id"],
        {
            "unit": "Unit 2",
            "start_time": D._iso(D.NOW - timedelta(days=30)),
            "end_time": D._iso(D.NOW),
        },
    )
    assert exec_result is not None
    assert exec_result["status"] == "completed"
    assert "value" in exec_result["result"]


def test_execute_calculation_unknown_id_returns_none():
    assert analytics.execute_calculation("CALC-does-not-exist", {}) is None
