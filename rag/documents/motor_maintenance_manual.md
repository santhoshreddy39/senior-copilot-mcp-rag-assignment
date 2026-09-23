---
title: Maintenance Manual MM-53 — Unit 5 Drive Motors
doc_type: maintenance-manual
applicable_assets: ["Motor M-305 Drive", "Motor M-306 Drive"]
applicable_asset_types: ["Induction Motor"]
tags: ["motor", "unit-5", "maintenance-manual", "trip"]
version: "1.4"
effective_date: "2025-11-20"
---

# MM-53 — Unit 5 Drive Motors (M-305 / M-306)

## 1. Equipment Overview

M-305 and M-306 are 1LA8-315 frame induction motors driving the Unit 5
process pumps. Both are protected by microprocessor-based motor protection
relays reporting overcurrent, ground fault, thermal overload, and
undervoltage trip flags.

## 2. Motor Trip — Diagnostic Sequence

A "Motor Trip" alarm means the protection relay has already opened the
breaker; the motor is stopped. Do not attempt to reset and restart until the
following sequence is complete:

1. **Read the relay target/flag** at the local MCC bucket or via the relay's
   HMI. This identifies the specific trip cause (overcurrent, ground fault,
   thermal, undervoltage, or mechanical/vibration interlock) and determines
   the rest of this sequence.
2. **Overcurrent or thermal trip**: check the driven equipment (pump/fan) for
   mechanical binding, a seized bearing, or blocked flow causing sustained
   overload before restoring power.
3. **Ground fault trip**: do not reset. This requires an electrical
   inspection (megger test) before the motor is re-energized.
4. **Undervoltage trip**: check upstream bus voltage and confirm no other
   large load started simultaneously (voltage dip from motor-starting
   inrush elsewhere on the same bus is a common cause).
5. Once the cause is identified and corrected, a single reset attempt is
   permitted. Two trips within 30 minutes on the same cause requires
   electrical/mechanical engineering sign-off before a further attempt —
   see Safety Instruction SI-11.

## 3. Recurring Motor Trips

If M-305 has tripped more than twice in a 90-day window, treat this as a
developing mechanical or electrical fault rather than a series of unrelated
events. Common findings in past investigations:

- Coupling misalignment developing gradually, showing up first as vibration
  alarms in the weeks before a trip.
- Bearing degradation, similarly preceded by rising winding/bearing
  temperature trend.
- Driven-equipment blockage recurring at a similar time of day/production
  cycle (check for a correlated upstream process alarm).

Always pull the vibration and winding-temperature alarm history for the 2
weeks preceding a motor trip — a trip is frequently the *last* alarm in a
sequence, not the first.

## 4. Related Equipment

M-305 and M-306 share the Unit 5 motor control center and a common cooling
water supply. A cooling water supply issue can produce correlated high
winding-temperature alarms on both motors.
