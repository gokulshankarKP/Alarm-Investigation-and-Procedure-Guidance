---
doc_id: TSG-CMP-002
title: Compressor Discharge Pressure Alarm Troubleshooting
doc_type: troubleshooting
revision: A
status: active
effective_date: 2026-04-05
asset_classes: [compressor]
asset_ids: [K-201, K-202, K-203]
alarm_codes: [CMP-DISCH-P-H, CMP-DISCH-P-HH, CMP-SURGE, CMP-INTERCOOL-T-H, CMP-DISCH-T-H]
sites: [EastRefinery]
trust_level: controlled
owner: Reliability Engineering
---

# Compressor Discharge Pressure Alarm Troubleshooting

## 1. Why discharge pressure alarms recur

Repeated `CMP-DISCH-P-H` alarms usually have one of five causes. Work through them in this
order, because the first two explain most recurring cases.

| # | Cause | Typical alarm pattern | Key evidence |
|---|---|---|---|
| 1 | Downstream restriction (PCV-210 sticking, fouled downstream exchanger, partially closed block valve) | Alarm on all running compressors at the same time | Header pressure high while flow falls; PCV-210 position not matching output |
| 2 | Alarm setpoint too close to normal operation | Many short alarms (< 2 min), chattering, no operator action taken | Normal discharge near 8.4 barg vs. H alarm at 8.6 barg; alarm clears by itself |
| 3 | Intercooler fouling | Slow increase in `CMP-INTERCOOL-T-H` over weeks, then discharge pressure and temperature alarms | Intercooler ΔT falling; cooling water ΔT normal |
| 4 | Load transfer from parallel compressor | Alarm on one compressor right after the other unloads or trips | Correlated trip or unload event seconds before |
| 5 | Pressure transmitter drift | Alarm on one compressor only; other indications normal | Compare PT reading with local gauge; last calibration date |

## 2. Diagnostic steps

1. **Correlate across compressors.** If K-201 and K-202 alarm within the same 15 minutes, suspect
   a common downstream cause (1). If only one alarms, suspect causes 4 or 5.
2. **Check alarm duration and count.** Many alarms shorter than 2 minutes that clear without
   action indicate a chattering or badly placed setpoint (2). Raise a rationalization request per
   ALM-PHIL-001 Section 8 instead of repeatedly acknowledging.
3. **Trend intercooler temperatures** for 90 days. A steady rise indicates fouling (3). Schedule
   intercooler cleaning at the next opportunity.
4. **Check PCV-210** stroke test results and positioner feedback.
5. **Verify the transmitter** against a calibrated gauge if the pattern is single-machine.

## 3. Recommended actions by cause

| Cause | Immediate | Permanent |
|---|---|---|
| Downstream restriction | Reduce load; open bypass under supervisor instruction | Repair PCV-210; clean exchanger |
| Setpoint too close | Continue operation; do not shelve without approval | Rationalize: add 0.1 bar deadband and 30 s on-delay, or review setpoint |
| Intercooler fouling | Increase cooling water flow if available | Chemical or mechanical cleaning |
| Load transfer | Stabilise with anti-surge valve | Review load-sharing controller tuning |
| Transmitter drift | Use local gauge reading | Recalibrate or replace transmitter |

## 4. What not to do

- Do not raise the HH trip setpoint to stop nuisance alarms. Trip setpoints are part of the
  safety design and only change through Management of Change.
- Do not start the spare compressor into an uncleared downstream restriction.
