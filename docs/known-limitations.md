# Known limitations and future improvements

## Known limitations

1. **LLM latency on CPU:** measured with `qwen3:8b` on this CPU-only machine:
   * generation ≈ 4 tokens/s, prompt processing ≈ 20–30 tokens/s;
   * one grounded answer takes about 3–5 minutes (the synthesis prompt is about 2k tokens);
   * `LLM_TIMEOUT_S` defaults to 600 s, and the GUI waits up to `BACKEND_TIMEOUT_S` (900 s).

   Ways around it:
   * use a GPU (seconds per answer);
   * use `OLLAMA_MODEL=qwen3:4b`, about 2x faster;
   * use `LLM_PROVIDER=none`, the instant deterministic composer.

   If the LLM times out, the copilot falls back automatically and shows a warning.
2. **Conversation memory is in-process** (LangGraph `InMemorySaver`). It is lost on backend restart and not shared across replicas. A Postgres checkpointer (`langgraph-checkpoint-postgres`) is the drop-in fix.
3. **Simulator, not a real alarm system.** The data is synthetic and deterministic, anchored at `ALARM_SIM_ANCHOR_TIME` (2026-09-30). `COPILOT_REFERENCE_TIME` aligns "last 90 days" with the seeded history. If you set it to real time, the windows drift away from the seed unless you use `ALARM_SIM_ANCHOR_TIME=now`.
4. **Static tokens.** Auth uses static bearer tokens for the MCP server and the API: no OAuth, no per-user authorisation, and no MCP tool-level RBAC. All tools are read-only, so no write-approval flow is needed. Ticket creation isn't implemented.
5. **Heuristic injection detection** catches instruction-like text in documents but not every paraphrase. The main protections are structural: quarantine, trust labels, the prompt contract, deterministic consistency rules and the output guard.
6. **Rule-based intent** covers the assignment's question families and the plant vocabulary (sites, asset tags, alarm-code prefixes). Very different phrasing depends on the LLM path.
7. **The hashing embedder is lexical.** It is used only for CI and offline tests; its similarity scores are not comparable to nomic's, so tests use a lower threshold.
8. **Correlation is co-occurrence only** (a lag window with support and confidence). There is no causal inference or Granger analysis.
9. **The priority-score "related active alarms" factor** counts alarms overlapping in time on connected assets, as a proxy.
10. **Demo video and screenshots are not produced automatically.** Record them with the steps in [`demo-script.md`](demo-script.md).

## Future improvements

**Platform and scale**
- Stream tokens and workflow progress from the backend (Server-Sent Events) so the GUI shows each tool call live.
- Use a Postgres checkpointer for conversation memory; add Redis caching for asset search and metadata.
- Add OpenTelemetry tracing (spans per graph node and MCP call) exported to Jaeger/Tempo, and Prometheus metrics for tool latency, error rate and retrieval confidence.

**Retrieval quality**
- Add a cross-encoder reranker, and grow the evaluation set (question → expected sections) with recall@k tracked in CI.

**Security and workflow**
- Add a second MCP server (maintenance/CMMS) with a *write* tool (create a work order) behind an explicit human-approval step in the GUI.
- Add OAuth 2.1 for MCP (the SDK supports token verifiers), per-tool authorisation and tenant scoping.
- Let users upload documents, with incremental ingestion and a document-trust workflow.
