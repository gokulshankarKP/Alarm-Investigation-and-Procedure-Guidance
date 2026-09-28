# API integration: Alarm Management API

## Contract source

The API contract is the Postman collections supplied with the assignment, copied to `test-data/postman/`:

* `Alarm-API-Simulator.postman_collection.json`: the full E2E baseline, 15 requests.
* `Alarm-API-Chaining.postman_collection.json`: 10 multi-step chaining flows, 32 requests.

The simulator (`apps/alarm-api-simulator`) implements that contract. It is validated in three ways:

* `tests/integration/test_postman_contract.py` replays every request, with Postman-style variable chaining.
* CI job `contract` runs **newman** against a live simulator.
* Locally: `make postman`. Last run: 47/47 requests OK, all test scripts passing.

## Endpoints

| Method | Path | Purpose | MCP tool |
|---|---|---|---|
| GET | `/health` | Liveness (public) | health checks |
| GET | `/assets/search?query&limit&site&unit&asset_class` | Ranked asset search (`match_score`, `exact_match`) | `search_assets` |
| GET | `/assets/{asset_id}/metadata` | Master data, criticality, related assets, maintenance | `get_asset_metadata` |
| GET | `/alarms?asset_id&site&unit&status&severity&alarm_code&start_time&end_time&page&page_size&sort_by&sort_order` | Alarm list with pagination | `get_alarms` |
| GET | `/alarms/{alarm_id}` | Alarm detail | `get_alarm_details` |
| POST | `/alarms/summary` | KPIs per group | `summarize_alarms` |
| POST | `/alarms/trends` | Bucketed metrics and trend direction | `get_alarm_trends` |
| POST | `/alarms/correlation` | Co-occurrence sequences and common-cause assets | `correlate_alarms` |
| POST | `/alarms/flood-analysis` | Flood windows (> N alarms in a rolling window) | `analyze_alarm_floods` |
| POST | `/alarms/rationalization-candidates` | Recurring, chattering, stale, no-action alarms | `find_rationalization_candidates` |
| POST | `/alarms/priority-score` | 0–100 dynamic priority (ALM-PHIL-001 §4 weights) | `score_alarm_priority` |
| POST | `/recommendations/operator-actions` | Rule-engine recommendations, related alarms, history | `get_operator_recommendations` |
| POST | `/calculation-code/generate` | Read-only calculation listing and `calculation_id` | `calculate_alarm_kpi` (step 1) |
| POST | `/calculation-code/execute` | Runs the built-in KPI implementation | `calculate_alarm_kpi` (step 2) |
| GET | `/analytics/kpi-definitions` | KPI formulas and targets | `list_kpi_definitions` |

Full request and response examples are in [`mcp-tool-catalog.md`](mcp-tool-catalog.md) and the simulator OpenAPI at `http://localhost:8000/docs`.

## Cross-cutting behaviour

**Authentication**
* `Authorization: Bearer <ALARM_API_TOKEN>`, compared in constant time.
* A missing or invalid token returns 401 with `{"error": {"code": "UNAUTHORIZED"}}`.

**Trace metadata**
* Request headers: `trace_id` (or `x-trace-id`), `x-client-id`, `x-metadata-tag`.
* They are echoed in the response headers (`trace_id`, `x-trace-id`, `x-request-id`, …) and in the body's `meta`, and written to the request log.
* A `trace_id` is generated when the request doesn't provide one.

**Pagination**
* Parameters: `page` (≥ 1) and `page_size` (1–200).
* The response includes `pagination: {page, page_size, total_items, total_pages, has_next}`.
* The connector's `list_all_alarms` follows `has_next` up to `MCP_MAX_PAGES`.

**Errors**
* Envelope: `{"error": {"code", "message", "details"}, "trace_id"}`.
* Codes: `VALIDATION_ERROR` (422), `BAD_REQUEST` (400), `UNAUTHORIZED` (401), `NOT_FOUND` (404), `RATE_LIMITED` (429 + `Retry-After`), `UPSTREAM_FAILURE` (5xx, injected), `INTERNAL_ERROR` (500).
* Request bodies use `extra="forbid"`, and time ranges are checked (start < end).

**Fault injection** (demo and tests; admin endpoints need the API token; set `ALARM_SIM_ENABLE_ADMIN=false` to disable)
* `POST /admin/faults {path_prefix, mode: error|timeout|rate_limit, status_code, count, delay_seconds}`
* `DELETE /admin/faults`
* `GET /admin/requests?trace_id=` shows the request log, which proves trace propagation.

**Security of KPI calculation**
* `generate` returns a read-only code listing.
* `execute` runs a built-in implementation, so no submitted code is ever evaluated.

## Seed data

The data is deterministic: `ALARM_SIM_SEED=42`, covering the 183 days before `ALARM_SIM_ANCHOR_TIME`, which defaults to 2026-09-30. That's about 620 alarms, and they tell stories the corpus can explain:

| Story | Evidence in data | Explained by |
|---|---|---|
| BFP-101 recurring cavitation | DA-101 `DA-LVL-L` → BFP-101 `BFP-SUCT-P-L` → `BFP-VIB-H` → sometimes `BFP-VIB-HH`, increasing over the last 60 days | TSG-BFP-002 §2–4, SOP-BFP-001 §5 |
| NorthPlant current upset | Active critical `BFP-SUCT-P-LL` and `BFP-VIB-HH` on BFP-102, active DA-101 low level | SOP-BFP-001 §5.2/5.4, SAF-002 |
| EastRefinery discharge pressure | K-201 and K-202 `CMP-DISCH-P-H` together after `PCV-210 PCV-POS-DEV`, many short unacknowledged alarms, rising intercooler temperature | TSG-CMP-002 causes 1–3 |
| Highest priority | Active `CMP-SURGE` on K-202, unacknowledged 25 minutes → score 83.3 (urgent) | ALM-PHIL-001 §3–4 |
| SouthPlant motor trips | `TR-VOLT-DIP` on TR-501, then `MTR-TRIP-OL` on M-501 and M-502 within 2 minutes | MM-MTR-001 §4 correlation rule |
| Unit 2 flood | 15 alarms in 7.4 minutes on 2026-06-12 | ALM-PHIL-001 §6 |
| Unsafe or outdated API recommendations | "restart tripped pump" (BFP-VIB-HH), "reset and restart immediately" (MTR-TRIP-OL), "start spare K-203" (CMP-DISCH-P-H) | MM-BFP-003 §6, MM-MTR-001 §5, TSG-CMP-002 §4 |

## Connector design (`connectors/alarm_api`)

`AlarmApiClient` is used by the MCP server and is independent of MCP.

**Every call**
* Sends the bearer token and the trace headers.
* Drops `None` parameters.
* URL-encodes path segments, so `../admin` cannot change the path.

**Retries**
* Retried: 429, 502, 503, 504, timeouts and transport errors.
* Backoff: exponential with jitter; `Retry-After` is honoured.
* Not retried: 401, 404 and 422.

**Error mapping**

| HTTP result | Error |
|---|---|
| 401 / 403 | `AlarmApiAuthError` |
| 404 | `AlarmApiNotFoundError` |
| 400 / 409 / 422 | `AlarmApiValidationError` |
| 429 | `AlarmApiRateLimitError` |
| 5xx | `AlarmApiUnavailableError` |
| timeout | `AlarmApiTimeoutError` |
| non-JSON or non-object body | `AlarmApiContractError` |

Each error carries `code`, `status_code`, `attempts`, `trace_id`, `endpoint` and `retryable`.

**Results**
* `ApiResult.meta()` reports the endpoint, status, attempts, the retry reasons and duration.
* This metadata flows into MCP `meta.api_calls` and on to the GUI trace.
