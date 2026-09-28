# Test evidence

**Run:** 2026-09-29, Windows 11, Python 3.12.10, local PostgreSQL 18 + pgvector.

**Command:** `python -m pytest --cov` (or `make coverage`).

## Result

```text
137 passed in 137.36s
TOTAL  3881 statements, 302 missed, 92% coverage
ruff check: All checks passed · ruff format --check: 92 files already formatted · mypy: no issues in 52 source files
newman: Alarm-API-Simulator 15/15 requests, 3/3 assertions · Alarm-API-Chaining 32/32 requests, 11/11 test scripts
```

The coverage report is in `docs/coverage/coverage.xml`. `make coverage` regenerates the HTML version in `docs/coverage/html/`; CI uploads it as the `coverage-report` artifact.

## Tests by suite

| File | Tests | Covers (assignment test categories) |
|---|---:|---|
| `tests/unit/test_simulator_api.py` | 19 | API contract: auth, trace echo, pagination, validation, analytics, fault injection, deterministic seed |
| `tests/unit/test_alarm_api_client.py` | 11 | **API client**: payload construction, headers, retries, timeouts, `Retry-After`, error mapping, pagination, response parsing |
| `tests/unit/test_mcp_server_tools.py` | 11 | **MCP server**: tool registration and discovery, schema validation, authentication headers, pagination, retries, API error mapping, trace propagation, output contract |
| `tests/unit/test_mcp_auth_and_observability.py` | 3 | MCP bearer auth, secret redaction, trace ids in logs |
| `tests/unit/test_intent.py` | 16 | **Tool selection / intent**, input validation of LLM output, follow-up context |
| `tests/unit/test_consistency_guard_synthesis.py` | 16 | **Citation formatting**, conflicting evidence rules, output guard, response parsing |
| `tests/unit/test_retrieval_plan.py` | 4 | **Retrieval filtering**, **prompt-injection handling** |
| `rag/tests/test_loader.py`, `test_chunker.py`, `test_embedder.py` | 18 | **Document ingestion**, **chunking**, **metadata capture**, embedding retries |
| `rag/tests/test_retrieval.py` | 7 | **Retrieval relevance**, filters, **no-result behaviour**, low confidence, citation correctness |
| `rag/tests/test_pgvector_integration.py` | 3 | Live pgvector: idempotent ingestion, filters and boosts, SQL-injection safety |
| `tests/integration/test_mcp_client_integration.py` | 9 | **MCP client**: server connectivity, discovery, invocation, invalid arguments, missing tools, **partial failure**, timeouts, auth failure |
| `tests/integration/test_orchestration.py` | 11 | **Orchestration**: multi-step MCP chains, MCP output passed into later tools, RAG in the same workflow, combined answer, partial source failure, **conflicting evidence**, MCP down, vector store down, memory, LLM validation and fallback |
| `tests/integration/test_postman_contract.py` | 2 | Both Postman collections replayed with variable chaining |
| `tests/e2e/test_acceptance_scenario.py` | 4 | **End-to-end**: backend request → MCP server → Alarm API → RAG → grounded response with citations (mandatory acceptance scenario), tool discovery and health, request validation, injection safety |
| `tests/e2e/test_gui.py` | 3 | GUI via Streamlit AppTest: empty state and tool discovery, full answer with panels, citations and trace, backend error state |

Integration and e2e tests run the simulator and the MCP server as **real HTTP servers in background threads**. The copilot connects through `langchain-mcp-adapters` over streamable HTTP, exactly as in production. Failures are injected through the simulator's `/admin/faults` endpoint.

## Coverage by module

| Module | Coverage |
|---|---:|
| `alarm_api_sim` (simulator) | 94–100% |
| `alarm_mcp` (server, models, auth, config) | 94–100% |
| `connectors/alarm_api` | 92–100% |
| `copilot` graph / intent / synthesis / guard / consistency / service / schemas | 92–100% |
| `copilot` mcp_gateway | 88% |
| `copilot` llm (Ollama provider exercised manually, not in CI) | 63% |
| `copilot` api (lifespan default wiring exercised by `docker compose` / manual runs) | 70% |
| `rag/retrieval` retriever / models | 100% |
| `rag/ingestion` | 82–100% |
| `copilot_ui` components / api client (HTTP client is mocked in GUI tests) | 75% / 39% |
| `shared/observability` | 83% |

## Manual verification with the real LLM and embeddings

These were run on 2026-09-29 against the live stack: qwen3:8b and nomic-embed-text on Ollama (CPU), with the pgvector index built from the real embeddings.

* Acceptance scenario with qwen3:8b (outputs in `test-data/examples/response_acceptance_bfp101_recurring_llm.md`):
  * 10 MCP steps and 8 cited sources.
  * The API recommendation "restart the tripped pump" is flagged as conflicting with MM-BFP-003 §6 / SOP-BFP-001 §5.2.
  * Wall time was about 4.3 minutes on CPU; synthesis was about 250 s of that.
* Retrieval calibration with nomic-embed-text:
  * off-topic questions score at most 0.53, on-topic ones at least 0.67, so the threshold is 0.62;
  * "cooling tower fan vibration" (no covering document) is correctly flagged as low confidence.
* Streamlit rendered through AppTest against the live backend with no exceptions: 5 tabs, 8 citations, a 7-step trace.
