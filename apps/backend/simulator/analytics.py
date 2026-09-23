"""
Business logic for the derived Alarm Management API endpoints (summary, trends,
correlation, flood analysis, rationalization candidates, priority scoring,
operator recommendations, calculation code). Kept separate from main.py so it
can be unit tested without spinning up FastAPI/HTTP.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import data as D

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=D.NOW.tzinfo)


def _in_range(alarm: dict, start: datetime, end: datetime) -> bool:
    st = _parse(alarm["start_time"])
    return st is not None and start <= st <= end


def filter_alarms(
    asset_ids: list[str] | None,
    start: datetime,
    end: datetime,
    severity: list[str] | None = None,
    unit: str | None = None,
    site: str | None = None,
) -> list[dict]:
    rows = D.ALARMS
    if asset_ids:
        asset_id_set = set(asset_ids)
        rows = [a for a in rows if a["asset_id"] in asset_id_set]
    if unit:
        rows = [a for a in rows if a["unit"] == unit]
    if site:
        rows = [a for a in rows if a["site"] == site]
    if severity:
        sev_set = {s.lower() for s in severity}
        rows = [a for a in rows if a["severity"] in sev_set]
    rows = [a for a in rows if _in_range(a, start, end)]
    return rows


def _ack_delay_minutes(alarm: dict) -> float | None:
    st, at = _parse(alarm["start_time"]), _parse(alarm["ack_time"])
    if st is None or at is None:
        return None
    return (at - st).total_seconds() / 60.0


def summarize(
    asset_ids: list[str] | None, start: datetime, end: datetime, severity: list[str] | None, group_by: list[str] | None
) -> dict:
    rows = filter_alarms(asset_ids, start, end, severity)
    group_field = (group_by or ["alarm_name"])[0]
    if group_field not in ("alarm_name", "asset_id", "severity", "unit"):
        group_field = "alarm_name"

    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r[group_field]].append(r)

    summary = []
    for key, group_rows in grouped.items():
        delays = [d for d in (_ack_delay_minutes(r) for r in group_rows) if d is not None]
        recurring = len(group_rows) >= 3
        summary.append(
            {
                "group_key": key,
                "group_by": group_field,
                "alarm_count": len(group_rows),
                "recurring_rate": round(len(group_rows) / max(1, (end - start).days or 1), 3),
                "is_recurring": recurring,
                "avg_ack_delay_minutes": round(statistics.mean(delays), 1) if delays else None,
                "severity_breakdown": dict(Counter(r["severity"] for r in group_rows)),
            }
        )
    summary.sort(key=lambda s: s["alarm_count"], reverse=True)
    return {
        "summary": summary,
        "total_alarm_count": len(rows),
        "time_range": {"start_time": D._iso(start), "end_time": D._iso(end)},
    }


def trends(asset_ids: list[str] | None, start: datetime, end: datetime, bucket: str, metrics: list[str] | None) -> dict:
    rows = filter_alarms(asset_ids, start, end)
    bucket_delta = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7)}.get(
        bucket, timedelta(days=1)
    )

    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for r in rows:
        st = _parse(r["start_time"])
        bucket_index = int((st - start) / bucket_delta)
        bucket_start = start + bucket_index * bucket_delta
        buckets[bucket_start].append(r)

    out = []
    for bstart in sorted(buckets.keys()):
        group_rows = buckets[bstart]
        delays = [d for d in (_ack_delay_minutes(r) for r in group_rows) if d is not None]
        out.append(
            {
                "bucket_start": D._iso(bstart),
                "bucket_end": D._iso(bstart + bucket_delta),
                "alarm_count": len(group_rows),
                "avg_ack_delay_minutes": round(statistics.mean(delays), 1) if delays else None,
            }
        )
    return {"bucket": bucket, "metrics": metrics or ["alarm_count"], "buckets": out}


def correlate(
    asset_ids: list[str] | None,
    start: datetime,
    end: datetime,
    correlation_method: str,
    lag_window_minutes: int,
    severity_threshold: str,
    min_support: int,
) -> dict:
    rows = filter_alarms(asset_ids, start, end)
    min_rank = SEVERITY_RANK.get(severity_threshold, 1)
    rows = [r for r in rows if SEVERITY_RANK.get(r["severity"], 1) >= min_rank]
    rows_sorted = sorted(rows, key=lambda r: r["start_time"])

    pair_counts: Counter[tuple[str, str]] = Counter()
    pair_lags: dict[tuple[str, str], list[float]] = defaultdict(list)
    lag = timedelta(minutes=lag_window_minutes)

    for i, a in enumerate(rows_sorted):
        a_start = _parse(a["start_time"])
        for b in rows_sorted[i + 1 :]:
            b_start = _parse(b["start_time"])
            if b_start - a_start > lag:
                break
            if a["alarm_name"] == b["alarm_name"]:
                continue
            key = tuple(sorted([a["alarm_name"], b["alarm_name"]]))
            pair_counts[key] += 1
            pair_lags[key].append((b_start - a_start).total_seconds() / 60.0)

    correlated_pairs = []
    for key, count in pair_counts.items():
        if count < min_support:
            continue
        a_name, b_name = key
        correlated_pairs.append(
            {
                "alarm_name_a": a_name,
                "alarm_name_b": b_name,
                "cooccurrence_count": count,
                "confidence": round(min(1.0, count / max(1, len(rows_sorted)) * 5), 3),
                "avg_lag_minutes": round(statistics.mean(pair_lags[key]), 1),
            }
        )
    correlated_pairs.sort(key=lambda p: p["cooccurrence_count"], reverse=True)

    related_assets = []
    if asset_ids:
        for aid in asset_ids:
            asset = D.ASSETS_BY_ID.get(aid)
            if not asset:
                continue
            for related_id in asset.related_asset_ids:
                related_asset = D.ASSETS_BY_ID.get(related_id)
                if not related_asset:
                    continue
                overlap = len([r for r in rows if r["asset_id"] == related_id])
                if overlap:
                    related_assets.append(
                        {
                            "asset_id": related_id,
                            "name": related_asset.name,
                            "relationship": "same-unit",
                            "alarm_overlap_count": overlap,
                        }
                    )
    related_assets.sort(key=lambda r: r["alarm_overlap_count"], reverse=True)

    return {
        "method": correlation_method,
        "lag_window_minutes": lag_window_minutes,
        "correlated_pairs": correlated_pairs,
        "related_assets": related_assets,
    }


def flood_analysis(
    unit: str, start: datetime, end: datetime, threshold_count: int, rolling_window_minutes: int
) -> dict:
    rows = filter_alarms(None, start, end, unit=unit)
    rows_sorted = sorted(rows, key=lambda r: r["start_time"])
    window = timedelta(minutes=rolling_window_minutes)

    flood_windows = []
    i = 0
    n = len(rows_sorted)
    while i < n:
        w_start = _parse(rows_sorted[i]["start_time"])
        w_end = w_start + window
        j = i
        count = 0
        while j < n and _parse(rows_sorted[j]["start_time"]) <= w_end:
            count += 1
            j += 1
        if count >= threshold_count:
            actual_end = _parse(rows_sorted[j - 1]["start_time"])
            flood_windows.append(
                {
                    "start": D._iso(w_start),
                    "end": D._iso(actual_end),
                    "alarm_count": count,
                    "peak_rate_per_min": round(count / max(1, rolling_window_minutes), 2),
                }
            )
            i = j
        else:
            i += 1

    return {
        "unit": unit,
        "threshold_count": threshold_count,
        "rolling_window_minutes": rolling_window_minutes,
        "is_flooding": len(flood_windows) > 0,
        "flood_windows": flood_windows,
        "total_alarms_in_range": len(rows),
    }


def rationalization_candidates(
    asset_ids: list[str] | None, start: datetime, end: datetime, recurrence_threshold: int, stale_minutes_threshold: int
) -> dict:
    rows = filter_alarms(asset_ids, start, end)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["asset_id"], r["alarm_name"])].append(r)

    candidates = []
    for (asset_id, alarm_name), group_rows in grouped.items():
        if len(group_rows) < recurrence_threshold:
            continue
        durations = []
        for r in group_rows:
            st, et = _parse(r["start_time"]), _parse(r["end_time"])
            if st and et:
                durations.append((et - st).total_seconds() / 60.0)
        avg_duration = round(statistics.mean(durations), 1) if durations else None
        is_stale = avg_duration is not None and avg_duration >= stale_minutes_threshold
        asset = D.ASSETS_BY_ID.get(asset_id)
        recommendation = (
            "Review alarm setpoint and consider rationalization — high recurrence with long-lived state"
            if is_stale
            else "Review alarm setpoint and root cause — recurring above threshold"
        )
        candidates.append(
            {
                "asset_id": asset_id,
                "asset_name": asset.name if asset else asset_id,
                "alarm_name": alarm_name,
                "occurrence_count": len(group_rows),
                "avg_duration_minutes": avg_duration,
                "is_stale": is_stale,
                "recommendation": recommendation,
            }
        )
    candidates.sort(key=lambda c: c["occurrence_count"], reverse=True)
    return {
        "recurrence_threshold": recurrence_threshold,
        "stale_minutes_threshold": stale_minutes_threshold,
        "candidates": candidates,
    }


def priority_score(alarm_id: str) -> dict | None:
    alarm = D.ALARMS_BY_ID.get(alarm_id)
    if not alarm:
        return None
    asset = D.ASSETS_BY_ID.get(alarm["asset_id"])
    severity_score = SEVERITY_RANK.get(alarm["severity"], 1) * 20
    criticality_score = {"low": 5, "medium": 10, "high": 15, "critical": 20}.get(
        asset.criticality if asset else "medium", 10
    )
    same_asset_alarms = D.alarms_for_asset(alarm["asset_id"])
    recurrence_count = len([a for a in same_asset_alarms if a["alarm_name"] == alarm["alarm_name"]])
    recurrence_score = min(20, recurrence_count * 2)
    status_score = 20 if alarm["status"] == "active" else 5

    total = min(100, severity_score + criticality_score + recurrence_score + status_score)
    if total >= 80:
        level = "P1"
    elif total >= 60:
        level = "P2"
    elif total >= 35:
        level = "P3"
    else:
        level = "P4"

    return {
        "alarm_id": alarm_id,
        "priority_score": total,
        "priority_level": level,
        "factors": {
            "severity_score": severity_score,
            "asset_criticality_score": criticality_score,
            "recurrence_score": recurrence_score,
            "status_score": status_score,
            "recurrence_count_90d": recurrence_count,
        },
    }


_ACTION_LIBRARY = {
    "High Discharge Pressure": [
        "Verify downstream valve position is not throttled or blocked.",
        "Check discharge pressure transmitter calibration against local gauge.",
        "Confirm recycle/minimum-flow line is not inadvertently closed.",
    ],
    "Low Suction Pressure": [
        "Check suction strainer for fouling or blockage.",
        "Verify upstream vessel level and suction valve alignment.",
        "Inspect for cavitation noise; reduce flow demand if suction NPSH margin is low.",
    ],
    "High Bearing Temperature": [
        "Check lubrication oil level, quality, and cooler performance.",
        "Inspect bearing for signs of wear at next opportunity.",
        "Reduce load if temperature continues to trend upward.",
    ],
    "High Vibration": [
        "Perform a vibration spectrum analysis to identify the dominant frequency.",
        "Check for coupling misalignment or looseness at mounting points.",
        "If vibration exceeds trip setpoint trajectory, prepare for controlled shutdown.",
    ],
    "Seal Leak Detected": [
        "Visually confirm leak at mechanical seal versus adjacent piping.",
        "Check seal flush system pressure and flow.",
        "Schedule seal inspection; avoid dry-running the pump.",
    ],
    "Low Flow": [
        "Confirm downstream demand and control valve position.",
        "Check for a partially closed block valve or strainer fouling.",
    ],
    "High Discharge Temperature": [
        "Check interstage/aftercooler cooling water flow and temperature.",
        "Verify no recycle valve is stuck open, causing re-compression heating.",
    ],
    "Surge Warning": [
        "Do not close downstream valves further; open anti-surge valve if not already modulating.",
        "Reduce speed/load gradually per the compressor operating procedure.",
    ],
    "Low Lube Oil Pressure": [
        "Check lube oil pump status and auxiliary pump auto-start.",
        "Verify oil cooler and filter differential pressure.",
        "Prepare for emergency shutdown if pressure continues to fall toward the trip setpoint.",
    ],
    "Motor Trip": [
        "Check protective relay target/flag to identify trip cause (overcurrent, ground fault, thermal).",
        "Inspect motor and driven equipment for mechanical binding before reset.",
        "Do not reset and restart without confirming the initiating cause has cleared.",
    ],
    "Motor Overload": [
        "Check driven equipment for mechanical binding or increased load.",
        "Verify motor current against nameplate rating and ambient conditions.",
    ],
    "High Winding Temperature": [
        "Check motor cooling fan and ventilation path for obstruction.",
        "Verify load is within rated service factor.",
    ],
    "High Differential Pressure": [
        "Schedule exchanger cleaning; fouling is the most likely cause.",
        "Verify flow is within design range on both sides.",
    ],
    "Low Outlet Temperature": [
        "Check upstream process temperature and bypass control valve position.",
    ],
    "High Column Pressure": [
        "Verify condenser cooling duty and overhead vapor rate.",
        "Confirm pressure control valve is responding; check for control valve failure.",
    ],
    "Low Reflux Flow": [
        "Check reflux pump status and reflux control valve position.",
        "Verify reflux drum level is adequate for pump NPSH.",
    ],
}


def operator_recommendations(
    alarm_id: str, include_related: bool, include_asset_context: bool, include_historical_pattern: bool
) -> dict | None:
    alarm = D.ALARMS_BY_ID.get(alarm_id)
    if not alarm:
        return None
    asset = D.ASSETS_BY_ID.get(alarm["asset_id"])
    actions = _ACTION_LIBRARY.get(
        alarm["alarm_name"],
        [
            "Review the applicable operating procedure for this alarm tag.",
            "Notify the responsible operator/engineer if the condition persists.",
        ],
    )
    result = {
        "alarm_id": alarm_id,
        "alarm_name": alarm["alarm_name"],
        "asset_id": alarm["asset_id"],
        "recommended_actions": [{"action": a, "priority": idx + 1} for idx, a in enumerate(actions)],
        "procedure_tags": alarm.get("procedure_tags", []),
    }
    if include_asset_context and asset:
        result["asset_context"] = {
            "name": asset.name,
            "asset_type": asset.asset_type,
            "criticality": asset.criticality,
            "last_maintenance_date": asset.last_maintenance_date,
        }
    if include_related and asset:
        result["related_assets_to_inspect"] = [
            {"asset_id": rid, "name": D.ASSETS_BY_ID[rid].name}
            for rid in asset.related_asset_ids
            if rid in D.ASSETS_BY_ID
        ]
    if include_historical_pattern:
        same = [a for a in D.alarms_for_asset(alarm["asset_id"]) if a["alarm_name"] == alarm["alarm_name"]]
        result["historical_pattern"] = {
            "occurrence_count_90d": len(same),
            "is_recurring": len(same) >= 3,
        }
    return result


_CALCULATIONS: dict[str, dict] = {}

_CALC_TEMPLATES = {
    "alarm_flood_index": (
        "def calculate(alarms, window_minutes=10, threshold=10):\n"
        '    """Alarm Flood Index = ratio of time spent in flood condition."""\n'
        "    flood_minutes = 0\n"
        "    total_minutes = window_minutes * len(alarms)\n"
        "    # ... rolling window flood detection ...\n"
        "    return flood_minutes / max(1, total_minutes)\n"
    ),
    "efficiency_index": (
        "def calculate(process_data):\n"
        '    """Equipment efficiency index from throughput vs. rated capacity."""\n'
        "    return process_data['actual_throughput'] / process_data['rated_capacity']\n"
    ),
    "nuisance_alarm_index": (
        "def calculate(alarms, stale_minutes_threshold=180):\n"
        '    """Fraction of alarms considered nuisance (short-lived, high recurrence)."""\n'
        "    nuisance = [a for a in alarms if a['duration_minutes'] < 1]\n"
        "    return len(nuisance) / max(1, len(alarms))\n"
    ),
}


def generate_calculation(calculation_type: str, filters: dict) -> dict:
    calc_id = f"CALC-{uuid.uuid4().hex[:12]}"
    code = _CALC_TEMPLATES.get(calculation_type, "def calculate(*args, **kwargs):\n    raise NotImplementedError\n")
    record = {
        "calculation_id": calc_id,
        "calculation_type": calculation_type,
        "filters": filters,
        "generated_code": code,
        "status": "ready",
    }
    _CALCULATIONS[calc_id] = record
    return record


def execute_calculation(calculation_id: str, filters: dict) -> dict | None:
    record = _CALCULATIONS.get(calculation_id)
    if not record:
        return None
    calc_type = record["calculation_type"]
    unit = filters.get("unit")
    start = _parse(filters.get("start_time")) or (D.NOW - timedelta(days=30))
    end = _parse(filters.get("end_time")) or D.NOW
    rows = filter_alarms(None, start, end, unit=unit) if unit else filter_alarms(None, start, end)

    if calc_type == "alarm_flood_index":
        flood = flood_analysis(unit or "Unit 2", start, end, threshold_count=10, rolling_window_minutes=10)
        value = round(len(flood["flood_windows"]) / max(1, (end - start).days or 1), 4)
    elif calc_type == "nuisance_alarm_index":
        short_lived = 0
        for r in rows:
            st, et = _parse(r["start_time"]), _parse(r["end_time"])
            if st and et and (et - st) < timedelta(minutes=2):
                short_lived += 1
        value = round(short_lived / max(1, len(rows)), 4)
    else:
        value = round(len(rows) / max(1, (end - start).days or 1), 4)

    return {
        "calculation_id": calculation_id,
        "status": "completed",
        "result": {"value": value, "unit_of_measure": "index", "sample_size": len(rows)},
        "execution_time_ms": 12,
    }


KPI_DEFINITIONS = [
    {
        "name": "alarm_count",
        "description": "Total number of alarms in the selected range.",
        "unit": "count",
        "formula": "COUNT(alarms)",
    },
    {
        "name": "recurring_rate",
        "description": "Alarms per day for a given group.",
        "unit": "alarms/day",
        "formula": "COUNT(alarms) / days_in_range",
    },
    {
        "name": "avg_ack_delay",
        "description": "Average time between alarm activation and operator acknowledgement.",
        "unit": "minutes",
        "formula": "AVG(ack_time - start_time)",
    },
    {
        "name": "alarm_flood_index",
        "description": "Fraction of time the unit spends in an alarm flood condition (ISA-18.2).",
        "unit": "ratio",
        "formula": "flood_minutes / total_minutes",
    },
    {
        "name": "nuisance_alarm_index",
        "description": "Fraction of alarms that are short-lived / chattering.",
        "unit": "ratio",
        "formula": "COUNT(alarms where duration < 2min) / COUNT(alarms)",
    },
]
