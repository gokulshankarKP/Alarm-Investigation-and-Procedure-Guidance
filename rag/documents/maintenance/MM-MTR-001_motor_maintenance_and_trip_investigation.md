---
doc_id: MM-MTR-001
title: Induction Motor Maintenance and Trip Investigation Manual
doc_type: maintenance_manual
revision: C
status: active
effective_date: 2026-01-20
asset_classes: [motor]
asset_ids: [M-101, M-102, M-501, M-502, M-503]
alarm_codes: [MTR-TRIP-OL, MTR-TRIP-EF, MTR-WDG-TEMP-H, MTR-WDG-TEMP-HH, MTR-VIB-H, MTR-PHASE-IMB, BFP-MOTOR-TRIP]
sites: [NorthPlant, SouthPlant]
trust_level: controlled
owner: Electrical Maintenance
---

# Induction Motor Maintenance and Trip Investigation Manual

## 1. Scope

Applies to LV and MV squirrel-cage induction motors, including the boiler feed pump drives
M-101/M-102 (NorthPlant) and the Unit 5 process motors M-501, M-502, M-503 (SouthPlant).

## 2. Protection and alarm settings (typical)

| Alarm / trip | Setting | Meaning |
|---|---|---|
| MTR-WDG-TEMP-H | 130 °C (RTD) | Winding running hot (class F insulation) |
| MTR-WDG-TEMP-HH | 145 °C | Trip to protect insulation |
| MTR-TRIP-OL | Thermal overload relay | Sustained overcurrent |
| MTR-TRIP-EF | Earth fault relay | Insulation failure to earth |
| MTR-PHASE-IMB | > 10 % current imbalance | Supply or winding problem |
| MTR-VIB-H | 4.5 mm/s RMS | Mechanical problem in motor or driven machine |

## 3. Preventive maintenance

| Task | Interval |
|---|---|
| Insulation resistance test (1 kV megger for LV, 5 kV for MV) | Annually and before restart after any earth-fault trip |
| Bearing regreasing | Per nameplate, typically every 4,000 h |
| Cooling fan and air path cleaning | Every 6 months |
| Terminal box inspection and torque check | Annually |
| Thermographic survey of MCC/switchgear | Annually |

## 4. Motor trip investigation — related assets to inspect

A motor trip is a symptom. The cause can sit in the motor, in the machine it drives, or in the
electrical supply. Inspect these related assets:

1. **The driven equipment** (pump, fan, compressor). Check for seizure, blockage, or process
   overload. A driven machine running beyond its rated point draws excess current and causes
   overload trips.
2. **The coupling.** Check for damage and misalignment.
3. **The motor starter / MCC cubicle and protection relay.** Record the trip reason and fault
   currents from the relay event log before resetting anything.
4. **The supply feeder and upstream transformer.** Check for voltage dips, phase loss, or other
   motors on the same bus tripping at the same time.
5. **The motor cooling path.** Blocked fan cowl or dirty fins cause winding temperature trips.

**Correlation rule:** if several motors on the same bus trip within a few minutes (for example
M-501 and M-502), suspect the common supply (feeder, transformer, bus voltage) before
individual motors.

### 4.1 By trip type

| Trip | First checks | Before restart |
|---|---|---|
| MTR-TRIP-OL (overload) | Driven machine load, process conditions, mechanical binding | Cause identified; motor cooled (see Section 5) |
| MTR-TRIP-EF (earth fault) | Insulation resistance test | IR > 100 MΩ (MV) or > 10 MΩ (LV); **never restart on an unexplained earth fault** |
| MTR-WDG-TEMP-HH | Cooling path, ambient, load | Winding below 80 °C |
| MTR-PHASE-IMB | Supply voltages, cable terminations | Imbalance corrected |

## 5. Restart limits

Repeated starts overheat the rotor. Unless the motor data sheet says otherwise:

- Maximum **2 starts in succession from cold**, or **1 start from hot** (hot means it ran within
  the last 60 minutes).
- After using these starts, wait **at least 60 minutes** before another start attempt.
- **After an overload or earth-fault trip, do not reset and restart until the trip cause has
  been identified.** A recommendation to "reset and restart immediately" is not consistent with
  this manual.

## 6. Escalation

Call electrical maintenance for any earth-fault trip, any repeated trip (2 or more in 24 hours),
or any trip together with a burning smell or visible damage.
