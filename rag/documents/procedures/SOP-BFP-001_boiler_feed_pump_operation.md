---
doc_id: SOP-BFP-001
title: Boiler Feed Pump Operating Procedure
doc_type: sop
revision: C
status: active
effective_date: 2026-03-01
asset_classes: [boiler_feed_pump, deaerator]
asset_ids: [BFP-101, BFP-102, DA-101]
alarm_codes: [BFP-VIB-H, BFP-VIB-HH, BFP-BRG-TEMP-H, BFP-BRG-TEMP-HH, BFP-SUCT-P-L, BFP-SUCT-P-LL, BFP-DISCH-P-L, BFP-MIN-FLOW-L, BFP-SEAL-LEAK-H, BFP-MOTOR-TRIP]
sites: [NorthPlant]
trust_level: controlled
owner: NorthPlant Operations, Unit 1
---

# Boiler Feed Pump Operating Procedure

## 1. Scope

This procedure covers the two multistage centrifugal boiler feed pumps in NorthPlant Unit 1:

| Tag | Role | Driver | Suction source | Discharge |
|---|---|---|---|---|
| BFP-101 | Duty | Motor M-101 (1.2 MW, 6.6 kV) | Deaerator DA-101 | Economiser inlet header |
| BFP-102 | Standby (auto-start) | Motor M-102 (1.2 MW, 6.6 kV) | Deaerator DA-101 | Economiser inlet header |

Each pump has a minimum-flow recirculation valve (FCV-101 / FCV-102) that returns flow to
DA-101 to protect the pump at low boiler demand.

**Related assets for any BFP alarm investigation:** the driving motor (M-101 / M-102), the
deaerator DA-101 (level and pressure), the recirculation valve, the lube oil system, and the
standby pump.

## 2. Hazards

Boiler feed water is at approximately 150 °C and up to 140 barg on the discharge side.
Leaks can flash to steam and cause severe burns. Follow SAF-001 before any intervention in
the field.

## 3. Normal operating limits

| Parameter | Normal | Alarm H / L | Alarm HH / LL (trip) |
|---|---|---|---|
| Bearing vibration (velocity, RMS) | < 4.5 mm/s | H: 7.1 mm/s | HH: 11.0 mm/s, pump trips |
| Bearing temperature | 55–75 °C | H: 85 °C | HH: 95 °C, pump trips |
| Suction pressure | 4.5–5.5 barg | L: 3.8 barg | LL: 3.2 barg, pump trips |
| Discharge pressure | 128–138 barg | L: 120 barg | — |
| Flow | 80–220 t/h | Min-flow L: 60 t/h | — |
| Mechanical seal leakage | < 10 drops/min | H: leak detection switch | — |

## 4. Start-up and changeover

1. Confirm DA-101 level is above 60 % and pressure is stable.
2. Confirm the recirculation valve is in AUTO.
3. Confirm lube oil pressure is above 1.2 barg on the pump to be started.
4. Start the pump from the DCS. Confirm discharge pressure rises within 10 seconds.
5. For a planned changeover, start the standby pump, confirm stable flow for 5 minutes, then
   stop the duty pump. Never run both pumps against a closed discharge.
6. Limit motor starts to those allowed in MM-MTR-001 Section 5.

## 5. Alarm response

### 5.1 BFP-VIB-H — high bearing vibration (priority 3, medium)

1. Check the vibration trend for the last 24 hours. A step change points to a mechanical
   event; a slow rise points to wear or misalignment.
2. Check suction pressure. Low suction pressure causes cavitation, which shows as high,
   noisy vibration (see TSG-BFP-002 Section 4).
3. Check flow. Operation below minimum flow causes recirculation vibration.
4. Request a portable vibration survey by the reliability team within the shift.

### 5.2 BFP-VIB-HH — very high vibration, trip (priority 2, high)

1. Confirm the standby pump has auto-started and boiler feed flow is restored.
   If it has not started within 30 seconds, start it manually.
2. Monitor boiler drum level. If drum level falls below the low alarm, follow SAF-002.
3. **Do not restart the tripped pump** until the reliability engineer has reviewed the
   vibration data and released it. See MM-BFP-003 Section 6.
4. Raise a maintenance notification with the vibration trend attached.

### 5.3 BFP-BRG-TEMP-H / HH — high bearing temperature

1. Check lube oil pressure and oil level in the bearing housing sight glass.
2. Check cooling water flow to the lube oil cooler.
3. On HH (trip), changeover to standby and follow MM-BFP-003 Section 4 before restart.

### 5.4 BFP-SUCT-P-L / LL — low suction pressure (LL: priority 1, critical)

1. Check DA-101 level and pressure immediately. Most low-suction events originate at the
   deaerator, not the pump.
2. Check the suction strainer differential pressure.
3. On LL, the pump trips to prevent cavitation damage. Restore DA-101 conditions before
   starting any pump. Follow SAF-002 if drum level is falling.

### 5.5 BFP-MOTOR-TRIP — drive motor trip (priority 2, high)

1. Confirm standby pump auto-start.
2. Read the protection relay trip reason at the MCC (overload, earth fault, phase imbalance).
3. Follow MM-MTR-001 Section 4 for the trip investigation. Do not reset and restart until
   the cause is identified.

### 5.6 BFP-MIN-FLOW-L — low flow

Confirm the recirculation valve has opened. If it is stuck closed, reduce load on the pump or
change over to the standby pump and raise a notification for the valve.

### 5.7 BFP-SEAL-LEAK-H — seal leakage

Inspect from a safe distance only (hot water hazard). If leakage is a steady stream,
changeover to standby and isolate the pump under SAF-001.

## 6. Shutdown

1. Ensure the standby pump is running or boiler demand allows shutdown.
2. Stop the pump from the DCS. Confirm the discharge non-return valve has closed (no reverse
   rotation).
3. For maintenance, isolate and drain under SAF-001.
