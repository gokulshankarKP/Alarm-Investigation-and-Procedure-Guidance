# Why are compressor discharge pressure alarms repeatedly occurring?

_intent: recurring_alarm_analysis · confidence: high · llm: {'provider': 'none', 'model': 'none', 'used': False} · tools: ['tools/list', 'search_assets', 'get_asset_metadata', 'get_alarms', 'get_alarms', 'summarize_alarms', 'get_alarm_trends', 'find_rationalization_candidates', 'correlate_alarms', 'get_operator_recommendations']_

### Summary
'compressor' resolves to K-201 (Process Gas Compressor K-201, EastRefinery Unit 2, criticality A) [T2]. 2 active alarm(s): CMP-SURGE on K-202 (critical, unacknowledged, 25 min); CMP-DISCH-P-H on K-201 (medium, acknowledged, 8 min) [T4]. 179 alarm(s) in the analysed window; most frequent: CMP-DISCH-P-H x141, CMP-INTERCOOL-T-H x22, CMP-DISCH-T-H x6, CMP-DISCH-P-HH x4 [T5]. Alarm count trend is increasing (12.2 -> 15.1 per bucket) [T7].

### Likely causes
- Alarms on PCV-210 (Header Pressure Control Valve PCV-210) precede alarms on K-201, K-202: possible common or upstream cause. [T9]
- K-201 CMP-DISCH-P-H is followed by K-202 CMP-DISCH-P-H within 15 min in 68% of cases (n=49, median lag 1.2 min) [T9]
- PCV-210 PCV-POS-DEV is followed by K-201 CMP-DISCH-P-H within 15 min in 100% of cases (n=28, median lag 3.5 min) [T9]
- CMP-DISCH-P-H on K-201 is a rationalization candidate (recurring, cleared_without_operator_action, 72 occurrences). [T8]
- Documented likely causes: Compressor Discharge Pressure Alarm Troubleshooting §1 (1. Why discharge pressure alarms recur). [S1]

### Recommended actions
- **immediate**: Check the downstream header pressure and the position of PCV-210. A closing or sticking downstream valve is the most frequent cause. [S2]
- **immediate**: Check whether the parallel compressor has just tripped or unloaded (load transfer). [S2]
- **short term**: Reduce compressor load via the capacity controller if pressure keeps rising. [S2]
- **immediate**: Check cooling water supply temperature and flow to the intercooler. [S3]
- **immediate**: A rising intercooler outlet temperature over weeks indicates fouling (see TSG-CMP-002). [S3]
- **immediate**: Confirm the compressor has tripped and the anti-surge valve has opened fully. [S5]
- **immediate**: Start the spare compressor K-203 only after the downstream restriction is identified and cleared; otherwise it will trip for the same reason. [S5]
- **short term**: Check downstream header pressure and PCV-210 position [T10] [S1]
- **short term**: Reduce compressor load via the capacity controller if pressure keeps rising [T10] [S2]

### API recommendations vs documents
- ❌ **Do not follow** API recommendation "Start the spare compressor K-203 immediately to share the load" [T10]: Documents say not to start the spare compressor until the downstream restriction is identified and cleared, otherwise it trips for the same reason. (This advice only exists in the superseded revision A.) [S5]

### Applicable procedures
- SOP-CMP-001 §3.1: Process Gas Compressor Operating Procedure: 3.1 CMP-DISCH-P-H — high discharge pressure (priority 3, medium) [S2]
- SOP-CMP-001 §3.4: Process Gas Compressor Operating Procedure: 3.4 CMP-DISCH-T-H / CMP-INTERCOOL-T-H — high temperature [S3]
- SOP-CMP-001 §3.2: Process Gas Compressor Operating Procedure: 3.2 CMP-DISCH-P-HH — discharge pressure trip (priority 2, high) [S5]

## Citations

- **[S1]** TSG-CMP-002 rev A §1: Compressor Discharge Pressure Alarm Troubleshooting (controlled, score 0.07848)
- **[S2]** SOP-CMP-001 rev B §3.1: Process Gas Compressor Operating Procedure (controlled, score 0.05978)
- **[S3]** SOP-CMP-001 rev B §3.4: Process Gas Compressor Operating Procedure (controlled, score 0.05932)
- **[S4]** SOP-CMP-001 rev B §2: Process Gas Compressor Operating Procedure (controlled, score 0.04027)
- **[S5]** SOP-CMP-001 rev B §3.2: Process Gas Compressor Operating Procedure (controlled, score 0.04026)
- **[S6]** TSG-CMP-002 rev A §3: Compressor Discharge Pressure Alarm Troubleshooting (controlled, score 0.04)
- **[S7]** TSG-CMP-002 rev A §2: Compressor Discharge Pressure Alarm Troubleshooting (controlled, score 0.03975)
- **[S8]** SOP-CMP-001 rev B §1: Process Gas Compressor Operating Procedure (controlled, score 0.03739)