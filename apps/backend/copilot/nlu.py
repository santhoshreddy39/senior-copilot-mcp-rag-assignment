"""
Intent detection and entity extraction for the alarm investigation copilot.

This is a deterministic, dependency-free heuristic layer — it does not call
an LLM — for two reasons documented in docs/design-decisions.md: (1) it needs
to work with zero configuration, so the app doesn't degrade just because no
API key is set, and (2) intent/entity extraction over a bounded domain (alarm
investigation questions) is exactly the kind of task a small rule set
generalizes well for, which keeps planning fast, testable, and auditable.

It is deliberately NOT a lookup table of a handful of sample questions —
intents are detected from general keyword/phrase categories and entities are
extracted with patterns that match any asset name, unit, or site, so a
differently-worded question about a different asset still plans correctly
(see tests/unit/test_nlu.py for cases with unfamiliar phrasing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    ACTIVE_ALARMS = "active_alarms"
    RECURRING_INVESTIGATION = "recurring_investigation"
    HIGHEST_PRIORITY = "highest_priority"
    RELATED_ASSETS = "related_assets"
    PROCEDURE_LOOKUP = "procedure_lookup"
    RECOMMENDATION_CONSISTENCY = "recommendation_consistency"
    FULL_INVESTIGATION = "full_investigation"  # default: broad multi-tool investigation


@dataclass
class ExtractedEntities:
    asset_phrase: str | None = None
    unit: str | None = None
    site: str | None = None
    days_back: int = 30
    severities: list[str] = field(default_factory=list)
    status: str | None = None


@dataclass
class NLUResult:
    raw_query: str
    intent: Intent
    entities: ExtractedEntities


_INTENT_RULES: list[tuple[Intent, list[str]]] = [
    (Intent.ACTIVE_ALARMS, [r"\bactive\b", r"\bcurrently (alarming|in alarm)\b", r"\bright now\b"]),
    (
        Intent.RECURRING_INVESTIGATION,
        [r"repeatedly", r"recurring", r"keep(s)? (occurring|happening|alarming)", r"why (are|is|does|do)", r"chatter"],
    ),
    (
        Intent.HIGHEST_PRIORITY,
        [r"highest priority", r"most (critical|urgent)", r"top priority", r"which alarm.*priority"],
    ),
    (Intent.RELATED_ASSETS, [r"related assets?", r"what else should be inspected", r"other (assets|equipment)"]),
    (
        Intent.RECOMMENDATION_CONSISTENCY,
        [r"consistent with", r"agree with", r"match(es)? the (manual|procedure)", r"compare"],
    ),
    (Intent.PROCEDURE_LOOKUP, [r"which (operating )?procedure", r"what procedure", r"applicable procedure"]),
]

_SEVERITY_WORDS = ["critical", "high", "medium", "low"]
_STATUS_WORDS = ["active", "acknowledged", "cleared", "shelved"]

# Known units/sites in the simulated dataset — see apps/backend/simulator/data.py.
# A production system would resolve these via a lookup service call instead of a
# fixed list; kept simple here since the simulator's site/unit set is small and stable.
_KNOWN_UNITS = [f"Unit {i}" for i in range(1, 6)]
_KNOWN_SITES = ["EastRefinery", "WestTerminal"]

_ASSET_TYPE_WORDS = ["pump", "compressor", "motor", "column", "heater", "exchanger"]

_DAYS_RE = re.compile(r"last (\d+)\s*day", re.IGNORECASE)

# Matches e.g. "Boiler Feed Pump 101", "Compressor C-201", "Motor M-305 Drive" —
# a run of Title-Case words optionally followed by an alphanumeric tag — as well as
# lowercase generic mentions of an asset type ("this motor trip alarm", "the compressor").
_PROPER_ASSET_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+(?:[A-Z][a-zA-Z0-9\-]*|\d+)){1,4})\b")


def _detect_intent(query: str) -> Intent:
    lowered = query.lower()
    for intent, patterns in _INTENT_RULES:
        if any(re.search(p, lowered) for p in patterns):
            return intent
    return Intent.FULL_INVESTIGATION


def _extract_asset_phrase(query: str) -> str | None:
    candidates = _PROPER_ASSET_RE.findall(query)
    # Prefer the longest candidate that contains an asset-type word, since that is
    # most likely to be an actual equipment name rather than an unrelated proper noun.
    typed_candidates = [c for c in candidates if any(t in c.lower() for t in _ASSET_TYPE_WORDS)]
    pool = typed_candidates or candidates
    if pool:
        return max(pool, key=len).strip()

    # Fall back to a bare lowercase asset-type mention, e.g. "this motor trip alarm".
    lowered = query.lower()
    for t in _ASSET_TYPE_WORDS:
        if t in lowered:
            return t
    return None


def _extract_entities(query: str) -> ExtractedEntities:
    unit = next((u for u in _KNOWN_UNITS if u.lower() in query.lower()), None)
    site = next((s for s in _KNOWN_SITES if s.lower() in query.lower()), None)
    severities = [s for s in _SEVERITY_WORDS if re.search(rf"\b{s}\b", query, re.IGNORECASE)]
    status = next((s for s in _STATUS_WORDS if re.search(rf"\b{s}\b", query, re.IGNORECASE)), None)

    days_match = _DAYS_RE.search(query)
    days_back = int(days_match.group(1)) if days_match else 30

    return ExtractedEntities(
        asset_phrase=_extract_asset_phrase(query),
        unit=unit,
        site=site,
        days_back=days_back,
        severities=severities,
        status=status,
    )


def analyze(query: str) -> NLUResult:
    return NLUResult(raw_query=query, intent=_detect_intent(query), entities=_extract_entities(query))
