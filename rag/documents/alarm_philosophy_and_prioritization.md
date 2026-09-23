---
title: Alarm Philosophy AP-01 — Prioritization and Rationalization Principles
doc_type: alarm-philosophy
applicable_assets: []
applicable_asset_types: []
tags: ["alarm-philosophy", "prioritization", "rationalization", "all-units"]
version: "2.0"
effective_date: "2025-09-01"
---

# AP-01 — Alarm Prioritization and Rationalization Principles

## 1. Priority Levels

- **P1 (highest)**: Immediate operator action required to prevent equipment
  damage, safety event, or environmental release. Typically critical-severity
  alarms on high or critical criticality assets.
- **P2**: Action required within the shift; degraded condition that will
  become P1 if not addressed.
- **P3**: Should be investigated but does not require immediate action.
- **P4**: Informational / low urgency.

Priority should combine alarm severity, asset criticality, and whether the
alarm is part of a recurring pattern — a single high-severity alarm on a
critical asset that has also recurred many times in the last 90 days should
be treated as higher priority than the severity tag alone would suggest.

## 2. Recognizing Rationalization Candidates

An alarm is a rationalization candidate — meaning the setpoint, or the alarm
itself, should be reviewed by the alarm management team rather than treated
as a new process event each time — when it meets any of:

- Occurs 5 or more times in a 90-day window on the same asset.
- Median duration is very short (chattering) relative to how long it takes an
  operator to acknowledge it, indicating the setpoint sits inside normal
  process variance.
- Median duration is very long (stale, e.g. over 180 minutes), indicating the
  alarm is not actionable or the condition is tolerated for long periods
  without consequence, undermining the alarm's credibility.

## 3. Alarm Flooding

A unit is considered to be in an alarm flood when more than 10 alarms
activate within any rolling 10-minute window (per ISA-18.2 guidance). During
a flood, operators should prioritize P1 alarms only and defer investigation
of lower-priority alarms until the flood has cleared, since attempting to
address every alarm individually during a flood increases the risk of
missing the alarm that actually requires action.

## 4. Using API Recommendations Alongside Procedures

Automated recommendations (priority scoring, operator-action suggestions)
are decision support, not a replacement for the asset-specific operating
procedure or applicable safety instruction. Where an automated
recommendation and a written procedure appear to disagree, the written
procedure and safety instruction take precedence, and the discrepancy should
be reported to the alarm management team for review.
