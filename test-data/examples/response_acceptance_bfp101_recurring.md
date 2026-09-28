# Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source evidence.

_intent: recurring_alarm_analysis · confidence: high · llm: {'provider': 'none', 'model': 'none', 'used': False} · tools: ['tools/list', 'search_assets', 'get_asset_metadata', 'get_alarms', 'get_alarms', 'summarize_alarms', 'get_alarm_trends', 'find_rationalization_candidates', 'correlate_alarms', 'get_operator_recommendations']_

### Summary
'Boiler Feed Pump 101' resolves to BFP-101 (Boiler Feed Pump 101, NorthPlant Unit 1, criticality A) [T2]. 1 active alarm(s): BFP-VIB-H on BFP-101 (medium, acknowledged, 42 min) [T4]. 9 alarm(s) in the analysed window; most frequent: BFP-VIB-HH x8, BFP-MOTOR-TRIP x1 [T5]. Alarm count trend is increasing (2.8 -> 5.0 per bucket) [T7].

### Likely causes
- Alarms on DA-101 (Deaerator 101) precede alarms on BFP-101: possible common or upstream cause. [T9]
- BFP-101 BFP-SUCT-P-L is followed by BFP-101 BFP-VIB-H within 15 min in 100% of cases (n=19, median lag 3.0 min) [T9]
- DA-101 DA-LVL-L is followed by BFP-101 BFP-SUCT-P-L within 15 min in 95% of cases (n=19, median lag 2.0 min) [T9]
- Documented likely causes: Boiler Feed Pump Troubleshooting Guide §3 (3. BFP-VIB-H / BFP-VIB-HH — high vibration). [S2]

### Recommended actions
- **immediate**: Confirm standby pump auto-start. [S1]
- **immediate**: Read the protection relay trip reason at the MCC (overload, earth fault, phase imbalance). [S1]
- **short term**: Follow MM-MTR-001 Section 4 for the trip investigation. Do not reset and restart until the cause is identified. [S1]
- **short term**: Attempt to start the available boiler feed pump (BFP-101 or BFP-102) that did not trip on a mechanical protection. Do not restart a pump that tripped on BFP-VIB-HH or BFP-BRG-TEMP-HH. [S3]
- **short term**: Reduce boiler firing rate to minimum to slow the fall in drum level. [S3]
- **short term**: Announce the emergency to the shift supervisor. [S3]
- **immediate**: Confirm the standby pump has auto-started and boiler feed flow is restored. If it has not started within 30 seconds, start it manually. [S5]
- **short term**: Confirm the standby pump auto-started and boiler feedwater flow is restored [T10] [S5]
- **short term**: Monitor boiler drum level closely [T10] [S5]

### API recommendations vs documents
- ❌ **Do not follow** API recommendation "Reset the vibration trip and restart the tripped pump after 10 minutes if the vibration reading has returned to normal" [T10]: Controlled documents require the trip cause to be identified (and, for vibration trips, a reliability engineer review) before any reset or restart. [S1] [S3] [S5]

### Applicable procedures
- SOP-BFP-001 §5.5: Boiler Feed Pump Operating Procedure: 5.5 BFP-MOTOR-TRIP — drive motor trip (priority 2, high) [S1]
- SAF-002 §2: Emergency Response — Loss of Boiler Feedwater: 2. Immediate actions (first 2 minutes) [S3]
- SOP-BFP-001 §5.2: Boiler Feed Pump Operating Procedure: 5.2 BFP-VIB-HH — very high vibration, trip (priority 2, high) [S5]
- MM-BFP-003 §6: Boiler Feed Pump Maintenance Manual: 6. Return to service after a vibration trip (BFP-VIB-HH) [S6]

## Citations

- **[S1]** SOP-BFP-001 rev C §5.5: Boiler Feed Pump Operating Procedure (controlled, score 0.06027)
- **[S2]** TSG-BFP-002 rev B §3: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.05755)
- **[S3]** SAF-002 rev B §2: Emergency Response — Loss of Boiler Feedwater (controlled, score 0.05658)
- **[S4]** TSG-BFP-002 rev B §4: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.05588)
- **[S5]** SOP-BFP-001 rev C §5.2: Boiler Feed Pump Operating Procedure (controlled, score 0.04362)
- **[S6]** MM-BFP-003 rev A §6: Boiler Feed Pump Maintenance Manual (controlled, score 0.04208)
- **[S7]** SOP-BFP-001 rev C §5.1: Boiler Feed Pump Operating Procedure (controlled, score 0.04026)
- **[S8]** SOP-BFP-001 rev C §4: Boiler Feed Pump Operating Procedure (controlled, score 0.03868)