---
doc_id: TSG-BFP-002
title: Boiler Feed Pump Troubleshooting Guide
doc_type: troubleshooting
revision: B
status: active
effective_date: 2025-11-10
asset_classes: [boiler_feed_pump]
asset_ids: [BFP-101, BFP-102]
alarm_codes: [BFP-VIB-H, BFP-VIB-HH, BFP-BRG-TEMP-H, BFP-BRG-TEMP-HH, BFP-SUCT-P-L, BFP-SUCT-P-LL, BFP-SEAL-LEAK-H]
sites: [NorthPlant]
trust_level: controlled
owner: Reliability Engineering
---

# Boiler Feed Pump Troubleshooting Guide

## 1. How to use this guide

Start from the alarm code, then work through likely causes in order of probability. Always
correlate with related alarms: a vibration alarm that follows a suction pressure alarm is
almost always cavitation, not a mechanical fault.

## 2. Recurring high-severity alarms: first questions

When a BFP raises repeated high or critical alarms over weeks or months, answer these before
replacing parts:

1. **Do the alarms cluster in time with deaerator alarms?** Repeated DA-101 level or pressure
   excursions cause repeated low suction pressure and cavitation on the running pump.
2. **Do they follow load changes?** Rapid boiler load reductions push the pump toward minimum
   flow. If the recirculation valve responds slowly, vibration alarms follow.
3. **Do they occur only on one pump?** A pump-specific pattern points to wear, misalignment,
   or a bearing fault on that pump. A pattern on both pumps points to system causes
   (deaerator, suction strainer, control tuning).
4. **Did the pattern start after maintenance?** Post-maintenance misalignment and soft foot
   are common causes of new vibration alarms.

## 3. BFP-VIB-H / BFP-VIB-HH — high vibration

| Likely cause | Evidence | Check |
|---|---|---|
| Cavitation (low NPSH) | Suction pressure alarm before or with vibration; broadband noise; crackling sound | DA-101 level/pressure, suction strainer ΔP |
| Operation below minimum flow | Flow < 60 t/h; recirculation valve closed | Recirc valve position vs. demand |
| Misalignment | 2× running-speed component; high axial vibration; recent maintenance | Laser alignment check |
| Bearing wear | Rising trend over weeks; high-frequency bearing defect peaks | Vibration spectrum, oil analysis |
| Impeller imbalance or damage | 1× running-speed dominant | Spectrum; inspect at next outage |
| Loose foundation bolts / soft foot | Directional vibration difference | Torque check, soft-foot check |

## 4. Cavitation: the most common cause of recurring BFP alarms

Cavitation happens when suction pressure falls near the vapour pressure of the hot feed water.
Vapour bubbles collapse on the impeller, causing noise, vibration, and erosion.

Typical sequence seen in alarm history: `DA-LVL-L` or `DA-P-L` → `BFP-SUCT-P-L` →
`BFP-VIB-H` → possibly `BFP-VIB-HH` trip.

Corrective actions:

1. Stabilise deaerator level control (check DA-101 level control valve tuning).
2. Clean the suction strainer if ΔP exceeds 0.5 bar.
3. Review deaerator pressure control during load changes.

## 5. BFP-BRG-TEMP-H / HH — high bearing temperature

| Likely cause | Check |
|---|---|
| Low lube oil level or pressure | Sight glass, oil pressure < 1.2 barg |
| Degraded oil | Oil sample: water content, viscosity, particle count |
| Cooling water restriction | Cooler inlet/outlet temperature difference |
| Bearing damage | Vibration spectrum; temperature rising with vibration |
| Overload from misalignment | Alignment check |

## 6. BFP-SEAL-LEAK-H — seal leakage

Seal leakage that follows a cavitation event suggests the seal faces were damaged by dry
running or vibration. Replace the seal and investigate the cavitation root cause, otherwise
the leak will recur.

## 7. When to escalate

Escalate to the reliability engineer when:

- any trip occurs (VIB-HH, BRG-TEMP-HH, SUCT-P-LL, MOTOR-TRIP),
- the same high alarm recurs 3 or more times in 7 days, or
- vibration trend increases by more than 25 % in 30 days.
