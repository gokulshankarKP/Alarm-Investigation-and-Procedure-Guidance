# Which alarm has the highest priority in EastRefinery, and why?

_intent: priority_ranking · confidence: high · llm: {'provider': 'none', 'model': 'none', 'used': False} · tools: ['tools/list', 'get_alarms', 'score_alarm_priority', 'score_alarm_priority', 'score_alarm_priority', 'score_alarm_priority', 'get_operator_recommendations']_

### Summary
4 active alarm(s): CMP-SURGE on K-202 (critical, unacknowledged, 25 min); P-DISCH-P-L on P-402 (medium, unacknowledged, 50 min); PCV-POS-DEV on PCV-210 (medium, acknowledged, 15 min); CMP-DISCH-P-H on K-201 (medium, acknowledged, 8 min) [T2]. Highest dynamic priority: CMP-SURGE on K-202 (ALM-000612) scoring 83.3/100 (urgent) [T3]. Drivers: configured_severity 40.0, asset_criticality 25.0, duration_unacknowledged 15.0.

### Likely causes
- Documented likely causes: Compressor Discharge Pressure Alarm Troubleshooting §1 (1. Why discharge pressure alarms recur). [S3]

### Recommended actions
- **immediate**: Confirm the anti-surge valve has opened. If not, open it manually from the DCS immediately. [S1]
- **immediate**: Reduce discharge pressure setpoint or increase recycle flow until surge stops. [S1]
- **short term**: Repeated surge can destroy the thrust bearing and impeller; notify the reliability engineer. [S1]
- **immediate**: Confirm the compressor has tripped and the anti-surge valve has opened fully. [S2]
- **immediate**: Start the spare compressor K-203 only after the downstream restriction is identified and cleared; otherwise it will trip for the same reason. [S2]
- **short term**: Inform the shift supervisor and raise an event report. [S2]
- **immediate**: Check the downstream header pressure and the position of PCV-210. A closing or sticking downstream valve is the most frequent cause. [S7]
- **short term**: Confirm the anti-surge valve has opened; if not, open it manually from the DCS immediately [T7] [S1]
- **short term**: Reduce the discharge pressure setpoint or increase recycle flow until surge stops [T7] [S1]

### Applicable procedures
- SOP-CMP-001 §3.3: Process Gas Compressor Operating Procedure: 3.3 CMP-SURGE — surge detected (priority 1, critical) [S1]
- SOP-CMP-001 §3.2: Process Gas Compressor Operating Procedure: 3.2 CMP-DISCH-P-HH — discharge pressure trip (priority 2, high) [S2]
- SOP-CMP-001 §3.1: Process Gas Compressor Operating Procedure: 3.1 CMP-DISCH-P-H — high discharge pressure (priority 3, medium) [S7]

## Citations

- **[S1]** SOP-CMP-001 rev B §3.3: Process Gas Compressor Operating Procedure (controlled, score 0.04208)
- **[S2]** SOP-CMP-001 rev B §3.2: Process Gas Compressor Operating Procedure (controlled, score 0.03975)
- **[S3]** TSG-CMP-002 rev A §1: Compressor Discharge Pressure Alarm Troubleshooting (controlled, score 0.03951)
- **[S4]** SOP-CMP-001 rev B §2: Process Gas Compressor Operating Procedure (controlled, score 0.03773)
- **[S5]** TSG-CMP-002 rev A §3: Compressor Discharge Pressure Alarm Troubleshooting (controlled, score 0.03721)
- **[S6]** SOP-CMP-001 rev B §1: Process Gas Compressor Operating Procedure (controlled, score 0.0369)
- **[S7]** SOP-CMP-001 rev B §3.1: Process Gas Compressor Operating Procedure (controlled, score 0.03626)