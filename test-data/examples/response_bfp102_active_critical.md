# Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.

_intent: active_alarm_triage · confidence: high · llm: {'provider': 'none', 'model': 'none', 'used': False} · tools: ['tools/list', 'search_assets', 'get_asset_metadata', 'get_alarms', 'correlate_alarms', 'score_alarm_priority', 'get_operator_recommendations']_

### Summary
'Boiler Feed Pump 102' resolves to BFP-102 (Boiler Feed Pump 102, NorthPlant Unit 1, criticality A) [T2]. 1 active alarm(s): BFP-SUCT-P-LL on BFP-102 (critical, unacknowledged, 12 min) [T4]. Highest dynamic priority: BFP-SUCT-P-LL on BFP-102 (ALM-000616) scoring 90.0/100 (urgent) [T6]. Drivers: configured_severity 40.0, asset_criticality 25.0, duration_unacknowledged 15.0.

### Likely causes
- Documented likely causes: Boiler Feed Pump Troubleshooting Guide §2 (2. Recurring high-severity alarms: first questions). [S4]

### Recommended actions
- **immediate**: Check DA-101 level and pressure immediately. Most low-suction events originate at the deaerator, not the pump. [S1]
- **immediate**: Check the suction strainer differential pressure. [S1]
- **short term**: On LL, the pump trips to prevent cavitation damage. Restore DA-101 conditions before starting any pump. Follow SAF-002 if drum level is falling. [S1]
- **short term**: Check DA-101 deaerator level and pressure immediately [T7] [S1]
- **short term**: Check the suction strainer differential pressure [T7] [S1]
- **short term**: Restore DA-101 conditions before starting any boiler feed pump [T7] [S1]
- **short term**: If boiler drum level is falling, apply the loss-of-feedwater emergency response [T7] [S1]

### Applicable procedures
- SOP-BFP-001 §5.4: Boiler Feed Pump Operating Procedure: 5.4 BFP-SUCT-P-L / LL — low suction pressure (LL: priority 1, critical) [S1]

## Citations

- **[S1]** SOP-BFP-001 rev C §5.4: Boiler Feed Pump Operating Procedure (controlled, score 0.05868)
- **[S2]** SAF-002 rev B §4: Emergency Response — Loss of Boiler Feedwater (controlled, score 0.04387)
- **[S3]** SOP-BFP-001 rev C §3: Boiler Feed Pump Operating Procedure (controlled, score 0.03975)
- **[S4]** TSG-BFP-002 rev B §2: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.0395)
- **[S5]** SAF-002 rev B §1: Emergency Response — Loss of Boiler Feedwater (controlled, score 0.03902)
- **[S6]** TSG-BFP-002 rev B §4: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.03788)
- **[S7]** TSG-BFP-002 rev B §1: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.03776)
- **[S8]** TSG-BFP-002 rev B §6: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.03747)