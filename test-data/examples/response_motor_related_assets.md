# What related assets should be inspected for the motor trip on M-501?

_intent: related_assets · confidence: high · llm: {'provider': 'none', 'model': 'none', 'used': False} · tools: ['tools/list', 'search_assets', 'get_asset_metadata', 'get_alarms', 'get_alarms', 'summarize_alarms', 'correlate_alarms', 'get_operator_recommendations']_

### Summary
'M-501' resolves to M-501 (Process Motor M-501, SouthPlant Unit 5, criticality A) [T2]. 1 active alarm(s): MTR-TRIP-OL on M-501 (high, acknowledged, 34 min) [T4]. 4 alarm(s) in the analysed window; most frequent: MTR-TRIP-OL x3, MTR-PHASE-IMB x1 [T5].

### Likely causes
- Alarms on TR-501 (Unit 5 Supply Transformer TR-501) precede alarms on M-501: possible common or upstream cause. [T7]
- TR-501 TR-VOLT-DIP is followed by M-501 MTR-TRIP-OL within 15 min in 100% of cases (n=3, median lag 1.0 min) [T7]
- M-501 MTR-TRIP-OL is followed by M-502 MTR-TRIP-OL within 15 min in 100% of cases (n=3, median lag 1.0 min) [T7]

### Recommended actions
- **follow up**: The driven equipment (pump, fan, compressor). Check for seizure, blockage, or process overload. A driven machine running beyond its rated point draws excess current and causes overload trips. [S3]
- **follow up**: The coupling. Check for damage and misalignment. [S3]
- **follow up**: The motor starter / MCC cubicle and protection relay. Record the trip reason and fault currents from the relay event log before resetting anything. [S3]
- **short term**: Check the driven pump for binding or process overload [T8] [S1]
- **short term**: Check the TR-501 supply and bus voltage: other motors on the same bus tripped at the same time [T8] [S3]

### API recommendations vs documents
- ❌ **Do not follow** API recommendation "Reset the overload relay and restart the motor immediately to restore production" [T8]: Controlled documents require the trip cause to be identified (and, for vibration trips, a reliability engineer review) before any reset or restart. [S1] [S4]

### Applicable procedures
- MM-MTR-001 §4: Induction Motor Maintenance and Trip Investigation Manual: 4. Motor trip investigation — related assets to inspect [S3]

## Citations

- **[S1]** MM-MTR-001 rev C §4.1: Induction Motor Maintenance and Trip Investigation Manual (controlled, score 0.05862)
- **[S2]** MM-MTR-001 rev C §2: Induction Motor Maintenance and Trip Investigation Manual (controlled, score 0.05613)
- **[S3]** MM-MTR-001 rev C §4: Induction Motor Maintenance and Trip Investigation Manual (controlled, score 0.04027)
- **[S4]** MM-MTR-001 rev C §5: Induction Motor Maintenance and Trip Investigation Manual (controlled, score 0.03837)
- **[S5]** MM-MTR-001 rev C §1: Induction Motor Maintenance and Trip Investigation Manual (controlled, score 0.03831)
- **[S6]** MM-MTR-001 rev C §3: Induction Motor Maintenance and Trip Investigation Manual (controlled, score 0.03764)