# Demo script (≤ 10 minutes)

**Setup:** start the stack with `docker compose up --build` or `python scripts/run_local.py`, then open http://localhost:8501.

**Before recording:** warm up the LLM with one question. On a CPU-only machine, either cut the waiting time in editing or run with `OLLAMA_MODEL=qwen3:4b`.

| Time | Show | What to point out |
|---|---|---|
| 0:00 | README architecture diagram | MCP path (blue) and RAG path (green), and the auth boundaries. The copilot has no API token, so it can reach the API only through MCP. |
| 0:45 | GUI sidebar | System health (MCP server, RAG index, LLM). **MCP tool discovery**: 13 tools; expand `correlate_alarms` to show its input and output schema. |
| 1:15 | While it runs | The **live tool activity** panel streams every stage and MCP call (`tool(args)` → ✓ with timings), Claude-style. |
| 1:30 | **Acceptance scenario**: "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days…" | See the three rows below. |
| | Answer | Causes cite the DA-101 correlation `[T#]` and TSG-BFP-002 `[S#]`. Actions cite SOP-BFP-001 §5.2 and MM-BFP-003 §6. |
| | Conflict check | The API recommendation "restart the tripped pump" is flagged as **Do not follow**. |
| | Tabs | Alarm summary (by-code chart, trend), Citations (controlled badges, scores), **MCP trace** (open `get_alarms`: arguments carry `asset_ids` from `search_assets` and the 90-day window; the response and upstream API calls are visible). |
| 4:00 | "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions." | Priority scores, critical BFP-SUCT-P-LL, SOP §5.4 and SAF-002 actions. |
| 4:45 | Follow-up: "Which operating procedure applies to this alarm?" | Conversation memory: the context warning, same asset and alarm. |
| 5:15 | "Which alarm has the highest priority in EastRefinery, and why?" | Several `score_alarm_priority` calls; CMP-SURGE on K-202 scores 83.3; ALM-PHIL-001 §4 cited. |
| 6:00 | "Why are compressor discharge pressure alarms repeatedly occurring?" | PCV-210 as the common cause, chattering and rationalization; TSG-CMP-002 cited. The **quarantined** vendor bulletin (prompt injection) appears in the Citations tab. |
| 7:00 | **Degraded scenario**: `curl -X POST localhost:8000/admin/faults -H "Authorization: Bearer <ALARM_API_TOKEN>" -H "Content-Type: application/json" -d '{"path_prefix":"/alarms/correlation","status_code":503,"count":20}'`, then ask the compressor question again | The trace shows `correlate_alarms` ❌ `UPSTREAM_UNAVAILABLE` with 🔁 retries, a degraded banner and warnings; the answer still comes from other tools and documents. Clear it with `curl -X DELETE localhost:8000/admin/faults -H "Authorization: Bearer <ALARM_API_TOKEN>"`. |
| 8:00 | Stop the MCP server (`docker compose stop alarm-mcp`), ask "Which operating procedure applies to BFP-VIB-HH?" | Documents-only answer with an "MCP server unreachable" warning. Restart it with `docker compose start alarm-mcp`. |
| 8:45 | Terminal: `make test` (or `pytest`), and `docs/test-evidence.md` | 137 tests, 92% coverage, the Postman contract and CI. |
| 9:30 | Wrap-up | Known limitations and future improvements. |
