"""Start the whole stack locally without Docker (cross-platform, incl. Windows).

    python scripts/run_local.py            # simulator, MCP server, backend, Streamlit GUI
    python scripts/run_local.py --ingest   # (re)index the documents first

Requires PostgreSQL + pgvector and Ollama as configured in .env (or RAG_BACKEND=memory,
EMBEDDING_PROVIDER=hash, LLM_PROVIDER=none for a fully offline run). Ctrl+C stops everything.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATHS = [ROOT, ROOT / "apps/alarm-api-simulator", ROOT / "apps/backend", ROOT / "apps/frontend", ROOT / "mcp-servers/alarm-management"]

SERVICES = [
    ("alarm-api", [sys.executable, "-m", "alarm_api_sim", "--port", "8000"], "http://127.0.0.1:8000/health"),
    ("alarm-mcp", [sys.executable, "-m", "alarm_mcp"], "http://127.0.0.1:9000/health"),
    ("backend", [sys.executable, "-m", "copilot"], "http://127.0.0.1:8080/health"),
    (
        "frontend",
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "apps/frontend/copilot_ui/app.py",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        "http://127.0.0.1:8501",
    ),
]


def wait_for(url: str, timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5):  # noqa: S310 - local health checks
                return True
        except OSError:
            time.sleep(1)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest", action="store_true", help="run python -m rag.ingestion first")
    args = parser.parse_args()

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in PATHS), "PYTHONIOENCODING": "utf-8"}
    if args.ingest:
        subprocess.run([sys.executable, "-m", "rag.ingestion"], cwd=ROOT, env=env, check=True)

    procs: list[subprocess.Popen] = []
    try:
        for name, cmd, health in SERVICES:
            print(f"starting {name}: {' '.join(cmd[1:])}")
            procs.append(subprocess.Popen(cmd, cwd=ROOT, env=env))  # noqa: S603 - fixed internal command list
            if not wait_for(health):
                print(f"{name} did not become healthy at {health}")
                return 1
            print(f"  {name} ready ({health})")
        print(
            "\nGUI:      http://127.0.0.1:8501\nBackend:  http://127.0.0.1:8080/docs\n"
            "MCP:      http://127.0.0.1:9000/mcp\nAlarm API http://127.0.0.1:8000/docs\nCtrl+C to stop."
        )
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
