---
title: Troubleshooting Guide TG-88 — Compressor Discharge Pressure and Surge Alarms
doc_type: troubleshooting-guide
applicable_assets: ["Compressor C-201 Discharge", "Compressor C-202 Discharge"]
applicable_asset_types: ["Centrifugal Compressor"]
tags: ["compressor", "discharge-pressure", "surge", "unit-2", "troubleshooting"]
version: "2.1"
effective_date: "2026-01-15"
---

# TG-88 — Compressor Discharge Pressure and Surge Alarms

## 1. Scope

Covers repeated/recurring High Discharge Pressure and Surge Warning alarms on
the Unit 2 centrifugal compressors (C-201, C-202). These two alarms are
frequently linked: a compressor pushed toward its surge line will often also
show elevated discharge pressure just before the surge control valve opens.

## 2. Why Discharge Pressure Alarms Recur

Recurring (chattering) high discharge pressure alarms are rarely a single
root cause. In order of frequency observed on C-201/C-202:

1. **Downstream demand swings** — a downstream user throttling or cycling a
   control valve causes discharge pressure to ride up and down across the
   alarm setpoint repeatedly. This produces many short-duration alarms
   rather than one sustained alarm — check alarm duration, not just count.
2. **Anti-surge valve tuning** — if the anti-surge controller is tuned too
   tight, it hunts, which shows up as coupled discharge-pressure and surge
   alarms in the same short window.
3. **Fouled interstage or discharge cooler** — gradually raises the baseline
   discharge pressure over days to weeks, causing the alarm to trip more and
   more often as ambient/process conditions vary, until cooler cleaning is
   performed.
4. **Alarm setpoint too tight for normal operating variance** — if the
   process consistently runs within 2-3% of the alarm setpoint, this is a
   rationalization candidate, not a process problem; see the alarm
   philosophy document.

## 3. Investigation Steps

1. Pull the alarm history for the compressor over the last 30-90 days and
   check whether occurrences cluster in time (points to a process/control
   issue) or are evenly spread (points to a setpoint/fouling issue).
2. Cross-reference with Surge Warning alarms on the same asset in the same
   window — high co-occurrence within a 15 minute window strongly suggests
   an anti-surge control tuning issue rather than independent faults.
3. Check discharge cooler differential temperature trend over the same
   period for a slow fouling signature.
4. Review whether a downstream unit was in a known transient (startup,
   turndown) during the alarm cluster.

## 4. Immediate Operator Actions

1. Do not close downstream block valves further while a surge warning is
   active — this pushes the machine closer to the surge line.
2. Confirm the anti-surge valve is modulating (not stuck) using the valve
   position feedback.
3. If discharge pressure continues to climb with the anti-surge valve fully
   open, reduce compressor speed/load per the compressor operating
   procedure rather than waiting for the high-high trip.

## 5. Related Assets

Compressor C-202 shares the same suction header as C-201; a sustained high
discharge pressure event on one machine can shift load abruptly to the other.
Both machines should be checked when either shows a sustained (not
chattering) discharge pressure alarm.
