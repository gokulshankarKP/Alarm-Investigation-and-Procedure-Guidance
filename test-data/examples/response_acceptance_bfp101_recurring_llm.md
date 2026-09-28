# Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source evidence.

_intent: recurring_alarm_analysis · confidence: high · llm: {'provider': 'ollama', 'model': 'qwen3:8b', 'used': True} · tools: ['tools/list', 'search_assets', 'get_asset_metadata', 'get_alarms', 'get_alarms', 'summarize_alarms', 'get_alarm_trends', 'find_rationalization_candidates', 'correlate_alarms', 'get_operator_recommendations']_

### Summary
Recurring high-severity alarms for BFP-101 over the last 90 days are primarily due to BFP-VIB-HH (Very high bearing vibration) and BFP-MOTOR-TRIP. These alarms are correlated with DA-101 issues, such as low level or pressure, leading to cavitation and vibration [T9]. The relevant operating procedure is SOP-BFP-001 rev C §5.5 and §5.2 [S1][S5].

### Likely causes
- Cavitation due to low suction pressure [T9] [S4]
- Low flow operation below minimum flow rate [S2]
- Bearing wear or misalignment [S2]
- Faulty vibration sensor or data acquisition [T10]

### Recommended actions
- **immediate**: Confirm standby pump auto-start and boiler feed flow is restored [S5]
- **immediate**: Monitor boiler drum level closely and follow SAF-002 if level falls below low alarm [S5]
- **short term**: Raise a maintenance notification with the vibration trend attached [S5]
- **follow up**: Review deaerator level control and check DA-101 level control valve tuning [S4]

### API recommendations vs documents
- ❌ **Do not follow** API recommendation "Reset the vibration trip and restart the tripped pump after 10 minutes if the vibration reading has returned to normal" [T10]: Controlled documents require the trip cause to be identified (and, for vibration trips, a reliability engineer review) before any reset or restart. [S1] [S3] [S5]
- API recommendations are mostly consistent with controlled documents, except for the suggestion to reset and restart the tripped pump without identifying the cause, which is not allowed per the documents.

### Applicable procedures
- SOP-BFP-001 §5.5: Guidance on confirming standby pump auto-start and trip investigation [S1]
- SOP-BFP-001 §5.2: Guidance on confirming standby pump auto-start, monitoring drum level, and not restarting the tripped pump without engineer review [S5]

## Citations

- **[S1]** SOP-BFP-001 rev C §5.5: Boiler Feed Pump Operating Procedure (controlled, score 0.06027)
- **[S2]** TSG-BFP-002 rev B §3: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.05755)
- **[S3]** SAF-002 rev B §2: Emergency Response — Loss of Boiler Feedwater (controlled, score 0.05658)
- **[S4]** TSG-BFP-002 rev B §4: Boiler Feed Pump Troubleshooting Guide (controlled, score 0.05588)
- **[S5]** SOP-BFP-001 rev C §5.2: Boiler Feed Pump Operating Procedure (controlled, score 0.04362)
- **[S6]** MM-BFP-003 rev A §6: Boiler Feed Pump Maintenance Manual (controlled, score 0.04208)
- **[S7]** SOP-BFP-001 rev C §5.1: Boiler Feed Pump Operating Procedure (controlled, score 0.04026)
- **[S8]** SOP-BFP-001 rev C §4: Boiler Feed Pump Operating Procedure (controlled, score 0.03868)