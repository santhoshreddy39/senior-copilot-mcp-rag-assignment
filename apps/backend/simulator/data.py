"""
Deterministic synthetic data generator for the Alarm Management API simulator.

The dataset is generated once at process start from a fixed random seed so
that responses are reproducible across runs and across the automated test
suite. The asset roster (Boiler Feed Pump 101/102, compressor discharge
pressure, EastRefinery, motor trip alarms, etc.) covers the sample questions
in the README so anyone trying them gets real data back, not an empty result.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SEED = 42
NOW = datetime(2026, 9, 22, 6, 0, 0, tzinfo=timezone.utc)

SEVERITIES = ["low", "medium", "high", "critical"]
STATUSES = ["active", "acknowledged", "cleared", "shelved"]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Asset:
    asset_id: str
    name: str
    asset_type: str
    unit: str
    site: str
    criticality: str
    manufacturer: str
    model: str
    install_date: str
    last_maintenance_date: str
    location: str
    tags: list[str]
    related_asset_ids: list[str] = field(default_factory=list)


@dataclass
class AlarmDef:
    alarm_name: str
    tag: str
    default_severity: str
    procedure_tags: list[str]
    description: str


ASSET_SEED = [
    dict(
        name="Boiler Feed Pump 101",
        asset_type="Centrifugal Pump",
        unit="Unit 3",
        site="EastRefinery",
        criticality="high",
        manufacturer="Sundyne",
        model="HPX-450",
        location="Boiler House / Level 1",
        tags=["pump", "boiler-feed", "rotating-equipment"],
    ),
    dict(
        name="Boiler Feed Pump 102",
        asset_type="Centrifugal Pump",
        unit="Unit 3",
        site="EastRefinery",
        criticality="high",
        manufacturer="Sundyne",
        model="HPX-450",
        location="Boiler House / Level 1",
        tags=["pump", "boiler-feed", "rotating-equipment"],
    ),
    dict(
        name="Compressor C-201 Discharge",
        asset_type="Centrifugal Compressor",
        unit="Unit 2",
        site="EastRefinery",
        criticality="critical",
        manufacturer="Elliott Group",
        model="YR-8",
        location="Compressor House / Bay 2",
        tags=["compressor", "discharge", "rotating-equipment"],
    ),
    dict(
        name="Compressor C-202 Discharge",
        asset_type="Centrifugal Compressor",
        unit="Unit 2",
        site="EastRefinery",
        criticality="high",
        manufacturer="Elliott Group",
        model="YR-8",
        location="Compressor House / Bay 2",
        tags=["compressor", "discharge", "rotating-equipment"],
    ),
    dict(
        name="Motor M-305 Drive",
        asset_type="Induction Motor",
        unit="Unit 5",
        site="EastRefinery",
        criticality="high",
        manufacturer="Siemens",
        model="1LA8-315",
        location="Motor Control Center / Unit 5",
        tags=["motor", "drive", "rotating-equipment"],
    ),
    dict(
        name="Motor M-306 Drive",
        asset_type="Induction Motor",
        unit="Unit 5",
        site="EastRefinery",
        criticality="medium",
        manufacturer="Siemens",
        model="1LA8-315",
        location="Motor Control Center / Unit 5",
        tags=["motor", "drive", "rotating-equipment"],
    ),
    dict(
        name="Cooling Water Pump 210",
        asset_type="Centrifugal Pump",
        unit="Unit 4",
        site="EastRefinery",
        criticality="medium",
        manufacturer="Flowserve",
        model="DVSX-6",
        location="Cooling Tower Area",
        tags=["pump", "cooling-water", "rotating-equipment"],
    ),
    dict(
        name="Feedwater Heater FWH-04",
        asset_type="Heat Exchanger",
        unit="Unit 3",
        site="EastRefinery",
        criticality="medium",
        manufacturer="Alfa Laval",
        model="M15-BFG",
        location="Boiler House / Level 2",
        tags=["heat-exchanger", "feedwater"],
    ),
    dict(
        name="Distillation Column DC-11",
        asset_type="Column",
        unit="Unit 1",
        site="WestTerminal",
        criticality="critical",
        manufacturer="Koch-Glitsch",
        model="Flexipac-350Y",
        location="Process Area 1",
        tags=["column", "distillation"],
    ),
    dict(
        name="Reflux Pump 118",
        asset_type="Centrifugal Pump",
        unit="Unit 1",
        site="WestTerminal",
        criticality="medium",
        manufacturer="Sundyne",
        model="LMV-311",
        location="Process Area 1",
        tags=["pump", "reflux", "rotating-equipment"],
    ),
]

ALARM_DEFS_BY_TYPE = {
    "Centrifugal Pump": [
        AlarmDef(
            "High Discharge Pressure",
            "PAH",
            "high",
            ["operating-procedure", "troubleshooting"],
            "Discharge pressure has exceeded the high alarm setpoint.",
        ),
        AlarmDef(
            "Low Suction Pressure",
            "PAL",
            "medium",
            ["operating-procedure", "troubleshooting"],
            "Suction pressure has fallen below the low alarm setpoint, risking cavitation.",
        ),
        AlarmDef(
            "High Bearing Temperature",
            "TAH",
            "high",
            ["maintenance-manual", "troubleshooting"],
            "Bearing temperature is above the high alarm setpoint.",
        ),
        AlarmDef(
            "High Vibration",
            "VAH",
            "critical",
            ["maintenance-manual", "safety-instruction"],
            "Vibration amplitude has exceeded the critical setpoint.",
        ),
        AlarmDef(
            "Seal Leak Detected",
            "LAH",
            "high",
            ["maintenance-manual", "safety-instruction"],
            "Mechanical seal leak detection has been triggered.",
        ),
        AlarmDef(
            "Low Flow",
            "FAL",
            "medium",
            ["operating-procedure"],
            "Flow rate has fallen below the minimum continuous flow setpoint.",
        ),
    ],
    "Centrifugal Compressor": [
        AlarmDef(
            "High Discharge Pressure",
            "PAH",
            "high",
            ["operating-procedure", "troubleshooting"],
            "Compressor discharge pressure has exceeded the high alarm setpoint.",
        ),
        AlarmDef(
            "High Discharge Temperature",
            "TAH",
            "high",
            ["troubleshooting", "maintenance-manual"],
            "Compressor discharge temperature has exceeded the high alarm setpoint.",
        ),
        AlarmDef(
            "Surge Warning",
            "SAH",
            "critical",
            ["safety-instruction", "operating-procedure"],
            "Compressor is operating close to the surge control line.",
        ),
        AlarmDef(
            "High Vibration",
            "VAH",
            "critical",
            ["maintenance-manual", "safety-instruction"],
            "Vibration amplitude has exceeded the critical setpoint.",
        ),
        AlarmDef(
            "Low Lube Oil Pressure",
            "PAL",
            "critical",
            ["safety-instruction", "maintenance-manual"],
            "Lube oil supply pressure has fallen below the critical trip approach setpoint.",
        ),
    ],
    "Induction Motor": [
        AlarmDef(
            "Motor Trip",
            "XA",
            "critical",
            ["troubleshooting", "operating-procedure"],
            "Motor has tripped on protective relay actuation.",
        ),
        AlarmDef(
            "Motor Overload",
            "IAH",
            "high",
            ["troubleshooting", "maintenance-manual"],
            "Motor current has exceeded the overload alarm setpoint.",
        ),
        AlarmDef(
            "High Winding Temperature",
            "TAH",
            "high",
            ["maintenance-manual"],
            "Stator winding temperature has exceeded the high alarm setpoint.",
        ),
        AlarmDef(
            "High Vibration",
            "VAH",
            "high",
            ["maintenance-manual"],
            "Vibration amplitude has exceeded the high alarm setpoint.",
        ),
    ],
    "Heat Exchanger": [
        AlarmDef(
            "High Differential Pressure",
            "PDAH",
            "medium",
            ["maintenance-manual", "troubleshooting"],
            "Differential pressure across the exchanger indicates fouling.",
        ),
        AlarmDef(
            "Low Outlet Temperature",
            "TAL",
            "medium",
            ["operating-procedure"],
            "Outlet temperature has fallen below the low alarm setpoint.",
        ),
    ],
    "Column": [
        AlarmDef(
            "High Column Pressure",
            "PAH",
            "critical",
            ["safety-instruction", "operating-procedure"],
            "Column pressure has exceeded the high alarm setpoint.",
        ),
        AlarmDef(
            "Low Reflux Flow",
            "FAL",
            "high",
            ["operating-procedure", "troubleshooting"],
            "Reflux flow has fallen below the minimum operating setpoint.",
        ),
    ],
}


def _asset_type_related_map() -> dict[str, list[str]]:
    """Assets are related when they share a unit and site (used for correlation/related-asset lookups)."""
    grouping: dict[tuple[str, str], list[str]] = {}
    for a in ASSETS:
        key = (a.unit, a.site)
        grouping.setdefault(key, []).append(a.asset_id)
    out: dict[str, list[str]] = {}
    for a in ASSETS:
        key = (a.unit, a.site)
        out[a.asset_id] = [x for x in grouping[key] if x != a.asset_id]
    return out


def _build_assets() -> list[Asset]:
    rng = random.Random(SEED)
    assets: list[Asset] = []
    for i, spec in enumerate(ASSET_SEED):
        asset_id = f"AST-{1000 + i}"
        install_days_ago = rng.randint(365 * 3, 365 * 12)
        maint_days_ago = rng.randint(10, 180)
        assets.append(
            Asset(
                asset_id=asset_id,
                name=spec["name"],
                asset_type=spec["asset_type"],
                unit=spec["unit"],
                site=spec["site"],
                criticality=spec["criticality"],
                manufacturer=spec["manufacturer"],
                model=spec["model"],
                install_date=_iso(NOW - timedelta(days=install_days_ago)),
                last_maintenance_date=_iso(NOW - timedelta(days=maint_days_ago)),
                location=spec["location"],
                tags=spec["tags"],
            )
        )
    return assets


ASSETS: list[Asset] = _build_assets()
ASSETS_BY_ID: dict[str, Asset] = {a.asset_id: a for a in ASSETS}
RELATED_ASSET_MAP = _asset_type_related_map()
for a in ASSETS:
    a.related_asset_ids = RELATED_ASSET_MAP.get(a.asset_id, [])


def _recurrence_weight(asset: Asset, alarm_def: AlarmDef) -> float:
    """
    Boosts recurrence for a few specific asset/alarm combinations so the data has a
    genuinely recurring pattern to find (e.g. compressor discharge-pressure alarms
    firing repeatedly) instead of a flat random distribution that never repeats.
    """
    if "Compressor" in asset.asset_type and alarm_def.alarm_name == "High Discharge Pressure":
        return 6.0
    if asset.name == "Boiler Feed Pump 102" and alarm_def.default_severity in ("high", "critical"):
        return 3.0
    if asset.name == "Motor M-305 Drive" and alarm_def.alarm_name == "Motor Trip":
        return 2.5
    return 1.0


# Assets/alarm-names guaranteed to have at least one currently ACTIVE alarm, so
# questions like "show active critical alarms for Boiler Feed Pump 102" or
# "highest priority active alarm in EastRefinery" are answerable on any run,
# without depending on how the random draw below happens to land.
GUARANTEED_ACTIVE = [
    ("Boiler Feed Pump 102", "High Vibration", "critical"),
    ("Boiler Feed Pump 102", "High Bearing Temperature", "high"),
    ("Compressor C-201 Discharge", "High Discharge Pressure", "high"),
    ("Compressor C-201 Discharge", "Surge Warning", "critical"),
    ("Motor M-305 Drive", "Motor Trip", "critical"),
    ("Boiler Feed Pump 101", "Low Suction Pressure", "medium"),
]


def _generate_alarms() -> list[dict]:
    rng = random.Random(SEED + 1)
    alarms: list[dict] = []
    window_start = NOW - timedelta(days=95)

    for asset in ASSETS:
        alarm_defs = ALARM_DEFS_BY_TYPE.get(asset.asset_type, [])
        for alarm_def in alarm_defs:
            weight = _recurrence_weight(asset, alarm_def)
            base_count = rng.randint(2, 5)
            occurrences = max(1, round(base_count * weight * rng.uniform(0.7, 1.3)))
            for _ in range(occurrences):
                offset_seconds = rng.randint(0, int((NOW - window_start).total_seconds()))
                start_time = window_start + timedelta(seconds=offset_seconds)
                duration_minutes = rng.randint(2, 240)
                is_still_active = (NOW - start_time) < timedelta(hours=6) and rng.random() < 0.35
                end_time = None if is_still_active else start_time + timedelta(minutes=duration_minutes)
                ack_delay_minutes = rng.randint(1, 45)
                ack_time = (
                    None
                    if is_still_active and rng.random() < 0.4
                    else start_time + timedelta(minutes=ack_delay_minutes)
                )
                severity = alarm_def.default_severity
                if rng.random() < 0.15:
                    severity = rng.choice(SEVERITIES)
                if is_still_active:
                    status = "active"
                elif ack_time is None:
                    status = "cleared"
                else:
                    status = rng.choice(["cleared", "cleared", "shelved"])

                alarm_id = f"ALM-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{asset.asset_id}-{alarm_def.alarm_name}-{start_time.isoformat()}-{_}')}"[
                    :24
                ]
                alarms.append(
                    {
                        "alarm_id": alarm_id,
                        "asset_id": asset.asset_id,
                        "asset_name": asset.name,
                        "alarm_name": alarm_def.alarm_name,
                        "tag": f"{asset.asset_id}.{alarm_def.tag}",
                        "severity": severity,
                        "status": status,
                        "unit": asset.unit,
                        "site": asset.site,
                        "start_time": _iso(start_time),
                        "end_time": _iso(end_time) if end_time else None,
                        "ack_time": _iso(ack_time) if ack_time else None,
                        "description": alarm_def.description,
                        "procedure_tags": alarm_def.procedure_tags,
                    }
                )

    # Guarantee a small set of currently-ACTIVE alarms so the sample questions
    # above are always answerable, regardless of the random draw above.
    asset_by_name = {a.name: a for a in ASSETS}
    for idx, (asset_name, alarm_name, severity) in enumerate(GUARANTEED_ACTIVE):
        asset = asset_by_name.get(asset_name)
        if not asset:
            continue
        alarm_def = next((d for d in ALARM_DEFS_BY_TYPE.get(asset.asset_type, []) if d.alarm_name == alarm_name), None)
        if not alarm_def:
            continue
        start_time = NOW - timedelta(minutes=rng.randint(5, 240))
        ack_time = None if rng.random() < 0.5 else start_time + timedelta(minutes=rng.randint(1, 20))
        alarm_id = f"ALM-{uuid.uuid5(uuid.NAMESPACE_DNS, f'active-{asset.asset_id}-{alarm_name}-{idx}')}"[:24]
        alarms.append(
            {
                "alarm_id": alarm_id,
                "asset_id": asset.asset_id,
                "asset_name": asset.name,
                "alarm_name": alarm_def.alarm_name,
                "tag": f"{asset.asset_id}.{alarm_def.tag}",
                "severity": severity,
                "status": "active",
                "unit": asset.unit,
                "site": asset.site,
                "start_time": _iso(start_time),
                "end_time": None,
                "ack_time": _iso(ack_time) if ack_time else None,
                "description": alarm_def.description,
                "procedure_tags": alarm_def.procedure_tags,
            }
        )

    alarms.sort(key=lambda a: a["start_time"], reverse=True)
    return alarms


ALARMS: list[dict] = _generate_alarms()
ALARMS_BY_ID: dict[str, dict] = {a["alarm_id"]: a for a in ALARMS}


def alarms_for_asset(asset_id: str) -> list[dict]:
    return [a for a in ALARMS if a["asset_id"] == asset_id]
