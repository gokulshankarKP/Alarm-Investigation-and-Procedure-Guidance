---
doc_id: SOP-CMP-001
title: Process Gas Compressor Operating Procedure
doc_type: sop
revision: B
status: active
effective_date: 2026-02-10
asset_classes: [compressor]
asset_ids: [K-201, K-202, K-203]
alarm_codes: [CMP-DISCH-P-H, CMP-DISCH-P-HH, CMP-DISCH-T-H, CMP-SURGE, CMP-VIB-H, CMP-LUBE-P-L, CMP-INTERCOOL-T-H]
sites: [EastRefinery]
trust_level: controlled
owner: EastRefinery Operations, Unit 2
---

# Process Gas Compressor Operating Procedure

## 1. Scope

Covers the three two-stage centrifugal process gas compressors in EastRefinery Unit 2.
K-201 and K-202 run in parallel; K-203 is the installed spare. Each compressor has an
intercooler between stages (E-201/E-202/E-203) and an anti-surge recycle valve
(UV-201/UV-202/UV-203).

**Related assets for compressor alarm investigation:** the intercooler and its cooling water
supply, the anti-surge valve, the downstream header and its pressure control valve PCV-210,
the drive motor, and the lube oil system.

## 2. Operating limits

| Parameter | Normal | Alarm H | Alarm HH (trip) |
|---|---|---|---|
| Discharge pressure | 7.4–8.2 barg | H: 8.6 barg | HH: 9.0 barg, compressor trips |
| Discharge temperature | 110–135 °C | H: 150 °C | HH: 165 °C, trip |
| Intercooler gas outlet temperature | 35–45 °C | H: 50 °C | — |
| Shaft vibration | < 40 µm pk-pk | H: 60 µm | HH: 85 µm, trip |
| Lube oil pressure | 1.8–2.2 barg | L: 1.4 barg | LL: 1.0 barg, trip |

The downstream header relief valve is set at 9.5 barg.

## 3. Alarm response

### 3.1 CMP-DISCH-P-H — high discharge pressure (priority 3, medium)

1. Check the downstream header pressure and the position of PCV-210. A closing or sticking
   downstream valve is the most frequent cause.
2. Check whether the parallel compressor has just tripped or unloaded (load transfer).
3. Reduce compressor load via the capacity controller if pressure keeps rising.
4. If the alarm is recurring, follow TSG-CMP-002.

### 3.2 CMP-DISCH-P-HH — discharge pressure trip (priority 2, high)

1. Confirm the compressor has tripped and the anti-surge valve has opened fully.
2. Start the spare compressor K-203 only after the downstream restriction is identified and
   cleared; otherwise it will trip for the same reason.
3. Inform the shift supervisor and raise an event report.

### 3.3 CMP-SURGE — surge detected (priority 1, critical)

1. Confirm the anti-surge valve has opened. If not, open it manually from the DCS immediately.
2. Reduce discharge pressure setpoint or increase recycle flow until surge stops.
3. Repeated surge can destroy the thrust bearing and impeller; notify the reliability engineer.

### 3.4 CMP-DISCH-T-H / CMP-INTERCOOL-T-H — high temperature

1. Check cooling water supply temperature and flow to the intercooler.
2. A rising intercooler outlet temperature over weeks indicates fouling (see TSG-CMP-002).

### 3.5 CMP-LUBE-P-L — low lube oil pressure

Confirm the auxiliary oil pump has started. Check the oil filter differential pressure and
reservoir level.

## 4. Start-up checklist (summary)

Lube oil pressure > 1.8 barg; anti-surge valve 100 % open; seal gas available; discharge
block valve open; downstream header below 8.0 barg.
