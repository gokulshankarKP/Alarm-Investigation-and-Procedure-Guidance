"""``python -m copilot [--host 0.0.0.0] [--port 8080]`` - run the copilot backend API."""

from __future__ import annotations

import argparse

import uvicorn

from copilot.config import CopilotSettings


def main() -> None:
    settings = CopilotSettings()
    parser = argparse.ArgumentParser(prog="python -m copilot")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()
    uvicorn.run("copilot.api:build_app", factory=True, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
