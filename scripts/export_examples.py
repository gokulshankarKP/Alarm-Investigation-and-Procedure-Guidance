"""Export example retrieved chunks, citations and full copilot responses to test-data/examples.

Needs the simulator + MCP server running and the pgvector index built:
    python scripts/export_examples.py [--llm]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-data" / "examples"

QUESTIONS = {
    "acceptance_bfp101_recurring": "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, "
    "identify likely contributing factors, retrieve the relevant operating procedure, and provide recommended actions "
    "with source evidence.",
    "bfp102_active_critical": "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.",
    "compressor_recurring": "Why are compressor discharge pressure alarms repeatedly occurring?",
    "eastrefinery_priority": "Which alarm has the highest priority in EastRefinery, and why?",
    "motor_related_assets": "What related assets should be inspected for the motor trip on M-501?",
    "out_of_scope": "What is the capital of France?",
}


async def main(use_llm: bool, only: list[str]) -> None:
    os.environ.setdefault("COPILOT_REFERENCE_TIME", "2026-09-30T00:00:00Z")
    os.environ["LLM_PROVIDER"] = "ollama" if use_llm else "none"
    from copilot.config import CopilotSettings
    from copilot.service import CopilotService
    from rag.retrieval import RetrievalFilters, create_retriever

    OUT.mkdir(parents=True, exist_ok=True)
    retriever = create_retriever()

    if not use_llm:
        samples = {}
        for name, (query, codes, flt) in {
            "procedure_for_BFP-VIB-HH": ("Which operating procedure applies to BFP-VIB-HH?", ["BFP-VIB-HH"], RetrievalFilters()),
            "compressor_recurrence_troubleshooting": (
                "Why are compressor discharge pressure alarms repeatedly occurring?",
                ["CMP-DISCH-P-H"],
                RetrievalFilters(doc_types=("troubleshooting",)),
            ),
            "off_topic_low_confidence": ("What is the capital of France?", [], RetrievalFilters()),
        }.items():
            res = retriever.search(query, filters=flt, alarm_codes=codes, top_k=3)
            samples[name] = {
                **res.to_dict(),
                "chunks": [{k: v for k, v in c.to_dict().items() if k != "content"} | {"content": c.content[:600]} for c in res.chunks],
            }
        (OUT / "retrieved_chunks.json").write_text(json.dumps(samples, indent=2, default=str), encoding="utf-8")

    service = CopilotService(CopilotSettings(), retriever=retriever)
    suffix = "_llm" if use_llm else ""
    for name, question in QUESTIONS.items():
        if only and name not in only:
            continue
        resp = await service.chat(question, f"conv-example-{name}")
        data = resp.model_dump(mode="json")
        for t in data["tool_trace"]:  # keep example files readable
            if isinstance(t["result"], dict) and len(json.dumps(t["result"])) > 4000:
                t["result"] = {"_truncated": True, "keys": list(t["result"].keys())}
        (OUT / f"response_{name}{suffix}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        (OUT / f"response_{name}{suffix}.md").write_text(
            f"# {question}\n\n_intent: {resp.intent} · confidence: {resp.confidence} · llm: {resp.llm} · "
            f"tools: {[t.tool for t in resp.tool_trace]}_\n\n{resp.answer_markdown}\n\n## Citations\n\n"
            + "\n".join(
                f"- **[{c.id}]** {c.doc_id} rev {c.revision} {c.section}: {c.title} ({c.trust_level}, score {c.score})"
                for c in resp.citations
            ),
            encoding="utf-8",
        )
        print(f"wrote {name}{suffix}: {resp.intent}, {len(resp.tool_trace)} tool steps, {len(resp.citations)} citations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    asyncio.run(main(args.llm, args.only))
