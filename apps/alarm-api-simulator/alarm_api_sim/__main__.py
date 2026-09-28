"""``python -m alarm_api_sim [--host 0.0.0.0] [--port 8000]``"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m alarm_api_sim")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("alarm_api_sim.main:build_app", factory=True, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
