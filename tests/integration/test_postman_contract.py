"""Replays every request of the Postman collections (the API contract) against the simulator.

Variables are substituted like Postman does, and values the collection scripts capture
(asset_id, alarm_id, calculation_id, flood window) are chained from the responses.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "test-data" / "postman"
COLLECTIONS = [ROOT / "Alarm-API-Simulator.postman_collection.json", ROOT / "Alarm-API-Chaining.postman_collection.json"]
COLLECTIONS = [c for c in COLLECTIONS if c.exists()]


def _requests(items):
    for item in items:
        if "item" in item:
            yield from _requests(item["item"])
        else:
            yield item


def _substitute(text: str, variables: dict) -> str:
    for _ in range(3):  # nested variables such as window_start -> {{start_time}}
        text = re.sub(r"\{\{(\w+)\}\}", lambda m: str(variables.get(m.group(1), m.group(0))), text)
    return text


def _capture(body: dict, variables: dict) -> None:
    results = body.get("results") or []
    if results:
        variables["asset_id"] = results[0]["asset_id"]
        variables["asset_id_2"] = (results[1] if len(results) > 1 else results[0])["asset_id"]
        variables["asset_id_3"] = (results[2] if len(results) > 2 else results[0])["asset_id"]
    if isinstance(body.get("data"), list) and body["data"]:
        variables["alarm_id"] = body["data"][0]["alarm_id"]
    if body.get("calculation_id"):
        variables["calculation_id"] = body["calculation_id"]
    if "flood_windows" in body:
        windows = body["flood_windows"]
        variables["window_start"] = windows[0]["start"] if windows else variables["start_time"]
        variables["window_end"] = windows[0]["end"] if windows else variables["end_time"]


@pytest.mark.skipif(not COLLECTIONS, reason="Postman collections not present")
@pytest.mark.parametrize("collection", COLLECTIONS, ids=lambda p: p.name)
def test_postman_collection_passes(collection, sim_client):
    spec = json.loads(collection.read_text(encoding="utf-8"))
    variables = {v["key"]: v["value"] for v in spec.get("variable", [])}
    failures = []
    count = 0
    for item in _requests(spec["item"]):
        req = item["request"]
        url = _substitute(req["url"]["raw"] if isinstance(req["url"], dict) else req["url"], variables)
        path = url.replace(variables["baseUrl"], "")
        headers = {h["key"]: _substitute(h["value"], variables) for h in req.get("header", [])}
        headers["Authorization"] = f"Bearer {variables['auth_token']}"
        body = req.get("body", {}).get("raw")
        response = sim_client.request(req["method"], path, headers=headers, content=_substitute(body, variables) if body else None)
        count += 1
        if response.status_code != 200:
            failures.append(f"{item['name']}: {response.status_code} {response.text[:200]}")
            continue
        payload = response.json()
        if "trace_id" in headers:
            assert response.headers["trace_id"] == headers["trace_id"]
        _capture(payload, variables)
    assert count >= 15 and not failures, failures
