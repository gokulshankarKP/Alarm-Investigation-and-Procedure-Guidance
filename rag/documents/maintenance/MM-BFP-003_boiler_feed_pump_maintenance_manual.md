---
doc_id: MM-BFP-003
title: Boiler Feed Pump Maintenance Manual
doc_type: maintenance_manual
revision: A
status: active
effective_date: 2025-09-01
asset_classes: [boiler_feed_pump]
asset_ids: [BFP-101, BFP-102]
alarm_codes: [BFP-VIB-HH, BFP-BRG-TEMP-HH, BFP-SEAL-LEAK-H, BFP-MOTOR-TRIP]
sites: [NorthPlant]
trust_level: controlled
owner: NorthPlant Maintenance
---

# Boiler Feed Pump Maintenance Manual

## 1. Equipment summary

Horizontal, multistage, barrel-type centrifugal pumps BFP-101 and BFP-102, each driven by a
1.2 MW, 6.6 kV induction motor through a flexible disc coupling. Tilting-pad thrust bearing
and sleeve journal bearings, forced lubrication from a shared lube oil console.

## 2. Preventive maintenance schedule

| Task | Interval | Performed by |
|---|---|---|
| Visual inspection, leak check, oil level | Daily | Operations |
| Portable vibration survey (both bearings, 3 axes) | Monthly | Reliability |
| Lube oil sample (water, viscosity, particle count) | Quarterly | Reliability |
| Coupling and alignment check (laser) | Annually, and after any motor or pump removal | Maintenance |
| Mechanical seal inspection | Every 16,000 running hours, or after any seal leak alarm | Maintenance |
| Bearing inspection | Every 24,000 running hours, or after any BRG-TEMP-HH trip | Maintenance |
| Full overhaul | Every 48,000 running hours | Maintenance + OEM |
| Standby pump test run | Weekly, 30 minutes | Operations |

Rotate duty between BFP-101 and BFP-102 monthly to equalise running hours.

## 3. Alignment tolerances

| Parameter | Tolerance at 2,980 rpm |
|---|---|
| Parallel (offset) misalignment | ≤ 0.05 mm |
| Angular misalignment | ≤ 0.05 mm / 100 mm |
| Soft foot | ≤ 0.05 mm on any foot |

Alignment must be done hot-compensated using the thermal growth values on the pump data sheet.

## 4. Actions after a bearing temperature trip (BFP-BRG-TEMP-HH)

1. Isolate the pump under SAF-001.
2. Take an oil sample before draining.
3. Inspect journal and thrust bearing pads for wiping or discolouration.
4. Check oil supply orifices and the lube oil filter.
5. Replace bearings if pad wiping exceeds 10 % of the contact area.

## 5. Mechanical seal replacement

Use only seal cartridges of the specified type. Before fitting a new seal after a leak, identify
the cause (cavitation, dry running, excessive vibration). Replacing a seal without correcting
the cause typically leads to a repeat failure within 3 months.

## 6. Return to service after a vibration trip (BFP-VIB-HH)

A pump that tripped on very high vibration **must not be restarted by operations alone**.
Before release:

1. The reliability engineer reviews the vibration trend and spectrum from the trip event.
2. If the root cause was a process condition (cavitation, low flow) that has been corrected,
   the engineer may release the pump for a supervised test run of 30 minutes with a portable
   analyser attached.
3. If the spectrum shows a mechanical fault (bearing defect, misalignment, imbalance), the pump
   stays out of service until repaired.
4. The release decision is recorded in the maintenance system.

Any automated recommendation to "restart the tripped pump" without this review is **not
consistent with this manual** and must not be followed.

## 7. Spare parts held on site

Mechanical seal cartridge (2), journal bearing set (1), thrust bearing pads (1 set), coupling
disc pack (1), lube oil filter elements (6).
