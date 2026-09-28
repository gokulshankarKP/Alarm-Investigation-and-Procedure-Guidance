# RAG Document Corpus — Alarm Investigation and Procedure Guidance Copilot

All documents in this folder are **synthetic**. They were written for this assessment and
do not describe any real plant, vendor, or ABB product. Setpoints and intervals are
realistic but illustrative; never use them to operate real equipment.

## Folder layout

| Folder | doc_type | Purpose |
|---|---|---|
| `philosophy/` | `alarm_philosophy` | Site-wide alarm priorities, response times, KPIs |
| `procedures/` | `sop` | Standard operating procedures and alarm response |
| `troubleshooting/` | `troubleshooting` | Likely causes and diagnostic checks per alarm |
| `maintenance/` | `maintenance_manual` | PM intervals, inspection and repair steps |
| `safety/` | `safety` | Safety rules that override any other guidance |
| `test_fixtures/` | various | Documents used by automated tests (injection, superseded revision) |

## Front-matter metadata schema

Every document starts with YAML front matter. The ingestion pipeline copies these fields
onto every chunk so retrieval can be filtered and citations can be built.

| Field | Type | Example | Used for |
|---|---|---|---|
| `doc_id` | string | `SOP-BFP-001` | Citation key |
| `title` | string | `Boiler Feed Pump Operating Procedure` | Citation display |
| `doc_type` | enum | `sop` | Retrieval filter |
| `revision` | string | `C` | Citation display |
| `status` | enum | `active` / `superseded` | Default filter: `status = active` |
| `effective_date` | date | `2026-03-01` | Freshness |
| `asset_classes` | list | `[boiler_feed_pump]` | Retrieval filter |
| `asset_ids` | list | `[BFP-101, BFP-102]` | Retrieval filter / boosting |
| `alarm_codes` | list | `[BFP-VIB-HH]` | Exact-match boosting (hybrid search) |
| `sites` | list | `[NorthPlant]` | Retrieval filter |
| `trust_level` | enum | `controlled` / `untrusted` | Prompt-injection handling |

## Alarm code convention (shared with the API simulator seed data)

`<ASSET-CLASS>-<MEASUREMENT>-<LEVEL>` where LEVEL is `L`, `LL`, `H`, `HH`, or `TRIP`.

| Prefix | Asset class | Example assets |
|---|---|---|
| `BFP` | Boiler feed pump | BFP-101, BFP-102 (NorthPlant, Unit 1) |
| `DA` | Deaerator | DA-101 (NorthPlant, Unit 1) |
| `CMP` | Process gas compressor | K-201, K-202, K-203 (EastRefinery, Unit 2) |
| `MTR` | LV/MV induction motor | M-501, M-502, M-503 (SouthPlant, Unit 5) |

## Sample questions this corpus supports

- "Which operating procedure applies to BFP-VIB-HH?" → SOP-BFP-001 §5, TSG-BFP-002 §3
- "Why are compressor discharge pressure alarms repeatedly occurring?" → TSG-CMP-002
- "What related assets should be inspected for this motor trip?" → MM-MTR-001 §4
- "Are the API recommendations consistent with the maintenance manual?" → MM-BFP-003 §6, MM-MTR-001 §5
- "Which alarm has the highest priority and why?" → ALM-PHIL-001 §3–4

## Test fixtures

- `test_fixtures/VB-CMP-099_vendor_bulletin_UNTRUSTED.md` contains **deliberate prompt-injection
  text**. Tests assert that the copilot never follows it and flags it.
- `test_fixtures/SOP-CMP-001_revA_SUPERSEDED.md` is an old revision with different setpoints.
  Tests assert it is excluded by the default `status = active` filter.
