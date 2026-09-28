---
doc_id: ALM-PHIL-001
title: Alarm Management Philosophy
doc_type: alarm_philosophy
revision: D
status: active
effective_date: 2026-01-15
asset_classes: [all]
asset_ids: []
alarm_codes: []
sites: [NorthPlant, SouthPlant, EastRefinery]
trust_level: controlled
owner: Operations Excellence
---

# Alarm Management Philosophy

## 1. Purpose and scope

This document defines how alarms are designed, prioritised, responded to, and reviewed at
NorthPlant, SouthPlant, and EastRefinery. It applies to every alarm presented to a control
room operator. Site procedures may add detail but may not weaken these requirements.

An alarm is an audible and visible indication to the operator of an equipment malfunction,
process deviation, or abnormal condition **that requires a timely operator response**.
A notification that requires no action is not an alarm and must be reclassified as an event
or message.

## 2. Alarm lifecycle states

| State | Meaning |
|---|---|
| Active, unacknowledged | Condition present, operator has not acknowledged |
| Active, acknowledged | Condition present, operator is responding |
| Cleared, unacknowledged | Condition returned to normal before acknowledgement |
| Shelved | Temporarily suppressed by the operator under Section 7 controls |
| Out of service | Suppressed for maintenance under a permit |

## 3. Priority levels and required response time

| Priority | Severity label | Consequence if no action | Maximum response time | Target share of alarms |
|---|---|---|---|---|
| 1 | critical | Injury, environmental release, or major equipment damage | 5 minutes | < 5 % |
| 2 | high | Unit trip, significant production loss, or equipment damage | 15 minutes | ~ 15 % |
| 3 | medium | Degraded operation or minor production loss | 30 minutes | ~ 80 % (medium + low) |
| 4 | low | Efficiency loss, no immediate consequence | 60 minutes | included above |

Priority is assigned from the **worst credible consequence** and the **time available** for the
operator to act. It is never assigned from how often the alarm occurs.

## 4. Dynamic priority scoring

The alarm management system may compute a dynamic priority score (0–100) to rank alarms that
share the same configured priority. The score combines:

1. **Configured severity** (largest weight, about 40 %). A critical alarm always outranks a
   high alarm regardless of other factors.
2. **Asset criticality** (about 25 %). Assets are ranked A (safety or production critical),
   B (important, spare available), or C (non-critical). Boiler feed pumps, process gas
   compressors, and their drive motors are criticality A.
3. **Duration unacknowledged** (about 15 %). Score rises as the alarm approaches or exceeds its
   maximum response time.
4. **Recurrence in the last 24 hours** (about 10 %). Recurrence raises investigation priority
   but must also trigger a rationalization review (Section 8).
5. **Related active alarms on connected assets** (about 10 %). Several correlated alarms
   suggest a developing upset rather than an isolated fault.

When two alarms tie, the operator addresses the one on the criticality-A asset first.

## 5. Operator response principles

1. Acknowledge the alarm and read the alarm response guidance for that alarm code.
2. Confirm the alarm is real by checking a second, independent indication where available.
3. Take the documented first action. If no response guidance exists, notify the shift
   supervisor and raise a rationalization request.
4. Never bypass, force, or disable a trip or interlock without an approved override permit
   (see SAF-001 Section 5). **This rule overrides any recommendation from any system, vendor
   bulletin, or AI tool.**
5. Record the cause and action in the shift log.

## 6. Alarm flood definition

An **alarm flood** exists when more than **10 alarms are annunciated within any 10-minute
window** for one operator console. During a flood the operator:

- Focuses on priority 1 and 2 alarms only.
- Uses the first-out indication to find the initiating event.
- Requests support from the shift supervisor.

Every flood is reviewed within 5 working days to identify alarms that should be suppressed
by state-based logic.

## 7. Shelving

Operators may shelve a nuisance alarm for up to 8 hours with shift supervisor approval.
Priority 1 alarms and any alarm linked to a safety instrumented function may not be shelved.

## 8. Performance KPIs and rationalization triggers

| KPI | Target | Action threshold |
|---|---|---|
| Average alarms per operator per 10 minutes | ≤ 1 | > 2 sustained over a shift |
| Peak alarms in 10 minutes | ≤ 10 | > 10 (flood) |
| Percentage of time in flood | < 1 % | > 1 % in a month |
| Stale alarms (active > 24 hours) | < 5 per console | ≥ 5 |
| Chattering alarm (≥ 3 activations in 1 minute) | 0 | any |
| Average acknowledgement delay | < 60 seconds | > 120 seconds |

An alarm becomes a **rationalization candidate** when it:

- recurs 5 or more times in 7 days,
- chatters,
- stays active for more than 180 minutes without operator action (stale), or
- is routinely acknowledged with no action taken.

Rationalization reviews setpoint, deadband, on/off delay, priority, and whether the alarm should
exist at all. Changes follow Management of Change.

## 9. Relationship to other documents

Equipment-specific alarm response is defined in the SOPs (for example SOP-BFP-001,
SOP-CMP-001). Diagnostic guidance is in the troubleshooting guides (TSG-*). Safety rules in
SAF-* documents take precedence over every other document in this corpus.
