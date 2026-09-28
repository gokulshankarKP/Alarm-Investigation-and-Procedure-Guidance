---
doc_id: SAF-002
title: Emergency Response — Loss of Boiler Feedwater
doc_type: safety
revision: B
status: active
effective_date: 2025-10-15
asset_classes: [boiler_feed_pump, deaerator, boiler]
asset_ids: [BFP-101, BFP-102, DA-101]
alarm_codes: [BFP-SUCT-P-LL, BFP-VIB-HH, BFP-MOTOR-TRIP, BLR-DRUM-LVL-L, BLR-DRUM-LVL-LL]
sites: [NorthPlant]
trust_level: controlled
owner: HSE Department / NorthPlant Operations
---

# Emergency Response — Loss of Boiler Feedwater

## 1. When this applies

Use this procedure when boiler feedwater flow is lost or insufficient, indicated by:

- both boiler feed pumps stopped or tripped, **or**
- the running pump tripped and the standby pump failed to start, **or**
- boiler drum level low alarm (`BLR-DRUM-LVL-L`) with feedwater flow below demand.

Low drum level exposes boiler tubes to overheating and can cause tube rupture. This is a
**priority 1** situation.

## 2. Immediate actions (first 2 minutes)

1. Attempt to start the available boiler feed pump (BFP-101 or BFP-102) that did **not** trip
   on a mechanical protection. Do not restart a pump that tripped on BFP-VIB-HH or
   BFP-BRG-TEMP-HH.
2. Reduce boiler firing rate to minimum to slow the fall in drum level.
3. Announce the emergency to the shift supervisor.

## 3. If feedwater is not restored

1. If drum level reaches `BLR-DRUM-LVL-LL`, the boiler trips automatically (master fuel trip).
   **Do not bypass the low-low level trip.**
2. After a low-low level trip, **do not add feedwater to a hot boiler** whose level has gone
   below the visible range until the boiler has been inspected and the supervisor authorises
   refill. Adding cold water to overheated tubes can cause rupture.

## 4. Deaerator-related loss of suction

If both pumps trip on `BFP-SUCT-P-LL`, the cause is almost always the deaerator DA-101
(low level or pressure). Restore DA-101 level and pressure first, then start one pump.

## 5. After the event

Complete an incident report within 24 hours and preserve alarm and trend data for the
investigation.
