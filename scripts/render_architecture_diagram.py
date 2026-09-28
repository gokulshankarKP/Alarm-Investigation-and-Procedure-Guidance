"""Render docs/architecture-diagram.png (MCP path and RAG path) with matplotlib.

python scripts/render_architecture_diagram.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture-diagram.png"

MCP = "#2563eb"
RAG = "#059669"
CORE = "#475569"
OBS = "#b45309"
SEC = "#dc2626"


def box(ax, x, y, w, h, title, lines=(), color=CORE, fill="#ffffff"):
    ax.add_patch(
        FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", linewidth=1.8, edgecolor=color, facecolor=fill, zorder=2)
    )
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=10.5, fontweight="bold", color=color, zorder=3)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.55 - i * 0.26, line, ha="center", va="top", fontsize=8.2, color="#1f2937", zorder=3)
    return (x, y, w, h)


def arrow(ax, start, end, label="", color=CORE, style="-|>", ls="-", offset=(0, 0.12), rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=14,
            linewidth=1.7,
            color=color,
            linestyle=ls,
            connectionstyle=f"arc3,rad={rad}",
            zorder=1,
        )
    )
    if label:
        mx, my = (start[0] + end[0]) / 2 + offset[0], (start[1] + end[1]) / 2 + offset[1]
        ax.text(
            mx,
            my,
            label,
            ha="center",
            va="bottom",
            fontsize=7.8,
            color=color,
            zorder=4,
            bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.9},
        )


def boundary(ax, x, y, w, h, label):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.2",
            linewidth=1.3,
            edgecolor=SEC,
            facecolor="none",
            linestyle=(0, (5, 4)),
            zorder=0,
        )
    )
    ax.text(x + 0.12, y + h - 0.08, label, ha="left", va="top", fontsize=8, color=SEC, style="italic")


def main() -> None:
    fig, ax = plt.subplots(figsize=(17, 10.5), dpi=150)
    ax.set_xlim(0, 17)
    ax.set_ylim(0, 10.5)
    ax.axis("off")
    ax.text(8.5, 10.25, "Alarm Investigation & Procedure Guidance Copilot: architecture", ha="center", fontsize=15, fontweight="bold")
    ax.text(
        8.5,
        9.9,
        "blue = MCP path (structured alarm data)   green = RAG path (documents)   dashed red = authentication / trust boundaries",
        ha="center",
        fontsize=9,
        color="#374151",
    )

    # UI
    box(
        ax,
        0.4,
        7.6,
        3.0,
        1.9,
        "Streamlit GUI",
        ["chat · alarm summary panel", "causes & actions · citations", "MCP trace (raw req/resp)", "tool discovery · health"],
    )
    # Backend / orchestration
    boundary(ax, 4.0, 2.3, 5.6, 7.3, "Copilot backend (FastAPI :8080)")
    box(
        ax,
        4.3,
        7.6,
        5.0,
        1.8,
        "Copilot orchestration (LangGraph)",
        [
            "understand → resolve_scope → collect_alarms",
            "→ analyze → recommend → retrieve",
            "→ check_consistency → synthesize → guard",
            "memory: checkpointer per conversation_id",
        ],
    )
    box(
        ax, 4.3, 5.4, 2.35, 1.7, "MCP client", ["langchain-mcp-adapters", "discovery · schema check", "timeouts · trace headers"], color=MCP
    )
    box(
        ax,
        6.95,
        5.4,
        2.35,
        1.7,
        "Retrieval service",
        ["hybrid: pgvector cosine", "+ full-text + exact codes", "filters · quarantine"],
        color=RAG,
    )
    box(
        ax,
        4.3,
        3.5,
        5.0,
        1.4,
        "Grounding & safety",
        ["API recs vs controlled docs (consistency)", "output guard · citation validation"],
        color=SEC,
    )

    # MCP server + API
    boundary(ax, 10.2, 6.6, 3.2, 3.0, "MCP bearer token")
    box(
        ax,
        10.4,
        6.8,
        2.8,
        2.5,
        "Alarm MCP server",
        ["FastMCP · streamable HTTP :9000", "13 typed read-only tools", "input/output validation", "error mapping · retries"],
        color=MCP,
    )
    boundary(ax, 13.8, 6.6, 3.0, 3.0, "Alarm API bearer token")
    box(
        ax,
        14.0,
        6.8,
        2.6,
        2.5,
        "Alarm Mgmt API",
        ["simulator (FastAPI :8000)", "contract: Postman collections", "assets · alarms · analytics", "recommendations · KPIs"],
        color=MCP,
    )
    box(ax, 10.4, 4.9, 2.8, 1.3, "Connector", ["AlarmApiClient (httpx)", "auth · trace · pagination"], color=MCP)

    # RAG ingestion
    box(
        ax,
        10.2,
        0.4,
        3.0,
        2.2,
        "RAG ingestion pipeline",
        ["load (YAML front matter)", "heading-aware chunking", "injection flagging · metadata", "embed (nomic-embed-text)"],
        color=RAG,
    )
    box(ax, 13.8, 0.4, 2.9, 2.2, "Document store", ["rag/documents (Markdown)", "SOP · TSG · MM · SAF", "philosophy · fixtures"], color=RAG)
    box(
        ax,
        6.95,
        0.4,
        2.8,
        2.2,
        "Retrieval index",
        ["PostgreSQL + pgvector", "rag_documents · rag_chunks", "HNSW + GIN (tsvector)"],
        color=RAG,
    )
    box(
        ax, 0.4, 0.4, 3.0, 2.2, "LLM (local, replaceable)", ["Ollama qwen3:8b", "intent + synthesis (JSON)", "LLM_PROVIDER=none → fallback"]
    )
    box(
        ax,
        0.4,
        4.2,
        3.0,
        2.6,
        "Observability",
        [
            "JSON logs, secrets redacted",
            "trace_id / conversation_id",
            "tool: duration, outcome,",
            "status, retries · retrieval scores",
            "LLM latency / tokens",
        ],
        color=OBS,
    )

    # arrows
    arrow(ax, (3.4, 8.55), (4.3, 8.55), "POST /api/chat", CORE)
    arrow(ax, (5.5, 7.6), (5.5, 7.1), "", MCP)
    arrow(ax, (8.1, 7.6), (8.1, 7.1), "", RAG)
    arrow(ax, (6.65, 6.3), (10.4, 7.9), "tools/list · tools/call\nx-trace-id, x-conversation-id", MCP, offset=(0, 0.05))
    arrow(ax, (11.8, 6.8), (11.8, 6.2), "", MCP)
    arrow(ax, (13.2, 5.55), (14.0, 7.4), "HTTPS + Bearer\ntrace_id · x-client-id · x-metadata-tag", MCP, offset=(0.9, -0.2))
    arrow(ax, (9.45, 5.6), (9.45, 2.6), "vector + keyword\n+ metadata filters", RAG, offset=(0.75, -0.9))
    arrow(ax, (13.8, 1.5), (13.2, 1.5), "", RAG)
    arrow(ax, (10.2, 1.5), (9.75, 1.5), "upsert chunks\n+ embeddings", RAG, offset=(0.0, 0.1))
    arrow(ax, (4.3, 3.7), (2.4, 2.6), "intent / answer (JSON)", CORE, offset=(0.1, 0.0))
    arrow(ax, (6.8, 5.4), (6.8, 4.9), "", SEC)
    arrow(ax, (4.3, 6.2), (3.4, 6.2), "logs", OBS, ls="--", offset=(0, 0.05))

    ax.text(
        4.3,
        3.15,
        "Flow: question → intent → MCP chain (asset → alarms → analytics →\n"
        "priority → recommendations) → RAG filtered by MCP results →\n"
        "consistency → grounded answer with [T#] / [S#] citations",
        fontsize=7.8,
        color="#111827",
        va="top",
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
