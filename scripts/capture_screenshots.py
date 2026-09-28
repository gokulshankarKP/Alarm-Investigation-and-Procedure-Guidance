"""Capture GUI screenshots into docs/screenshots (needs the stack running and `playwright install chromium`).

python scripts/capture_screenshots.py [--url http://localhost:8501]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
QUESTION = "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for an answer")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.goto(args.url, wait_until="networkidle")
        page.get_by_text("Ask about an asset").wait_for(timeout=30_000)
        page.screenshot(path=OUT / "01-home.png")

        page.get_by_placeholder("Ask about an alarm").fill(QUESTION)
        page.keyboard.press("Enter")
        page.get_by_text("search_assets(", exact=False).first.wait_for(timeout=60_000)
        page.wait_for_timeout(700)
        page.screenshot(path=OUT / "02-live-tool-activity.png")

        page.get_by_text("Used ", exact=False).first.wait_for(timeout=args.timeout * 1000)
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT / "03-answer.png", full_page=True)

        for tab, name in (("Overview", "04-overview"), ("Actions", "05-actions"), ("Sources", "06-sources"), ("Trace", "07-trace")):
            page.get_by_role("tab", name=tab).first.click()
            page.wait_for_timeout(800)
            page.screenshot(path=OUT / f"{name}.png", full_page=True)
        browser.close()
    print(f"screenshots in {OUT}")


if __name__ == "__main__":
    main()
