---
title: Operating Procedure OP-204 — Boiler Feed Pump Trains (Unit 3)
doc_type: operating-procedure
applicable_assets: ["Boiler Feed Pump 101", "Boiler Feed Pump 102"]
applicable_asset_types: ["Centrifugal Pump"]
tags: ["boiler-feed", "pump", "unit-3", "operating-procedure"]
version: "3.2"
effective_date: "2026-03-01"
---

# OP-204 — Boiler Feed Pump Trains (Unit 3)

## 1. Purpose

This procedure defines normal operation, alarm response, and switchover steps
for the Unit 3 boiler feed pump trains (Boiler Feed Pump 101 and Boiler Feed
Pump 102). BFP-101 and BFP-102 operate in a lead/standby configuration
feeding the Unit 3 steam drum through Feedwater Heater FWH-04.

## 2. Normal Operating Envelope

- Discharge pressure: 1550-1650 psig
- Suction pressure: 45-65 psig
- Bearing temperature: below 82 degC
- Minimum continuous flow: 180 gpm (recycle valve opens automatically below this)

## 3. High Discharge Pressure Alarm (PAH) Response

1. Confirm the reading against the local pressure gauge before taking action;
   a single transmitter fault should not be treated as a process upset.
2. Check that the downstream feedwater control valve is not throttled closed
   or that a manual block valve has not been left shut after maintenance.
3. Confirm the minimum-flow recycle valve is not stuck closed, which forces
   the pump toward shutoff head.
4. If pressure continues to rise toward the high-high trip setpoint (1800
   psig), prepare to switch to the standby pump per Section 5 before the trip
   activates, to avoid an unplanned feedwater interruption.

## 4. High Vibration / High Bearing Temperature Response

1. High vibration and high bearing temperature on a boiler feed pump are
   treated as a **potential mechanical fault**, not a process upset — do not
   attempt to "ride through" a high vibration alarm.
2. Check lubrication oil level and cooler differential temperature first;
   many bearing temperature excursions trace back to a fouled oil cooler.
3. If vibration exceeds the critical setpoint (per the alarm), or if bearing
   temperature continues to climb after 15 minutes, switch to the standby
   pump per Section 5 and remove the affected pump from service for
   vibration analysis. Do not run a pump with confirmed high vibration to
   failure — see Safety Instruction SI-11.

## 5. Lead/Standby Switchover

1. Verify the standby pump has been rotated within the last 7 days (auto-run
   test) and shows no active alarms.
2. Slowly open the standby pump discharge valve while throttling the
   running pump, maintaining steam drum level within +/- 2 inches throughout
   the transfer.
3. Once the standby pump is carrying full load, stop the affected pump and
   place it in standby / maintenance hold as appropriate.
4. Log the switchover reason and notify the shift supervisor.

## 6. Related Equipment

Feedwater Heater FWH-04 is downstream of both boiler feed pumps. A high
differential pressure alarm on FWH-04 can cause an apparent high discharge
pressure reading at the pump and should be checked as part of any
discharge-pressure investigation.
