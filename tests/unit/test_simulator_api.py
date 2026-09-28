"""Alarm Management API simulator: contract behaviour (auth, trace headers, pagination, errors, analytics)."""

from conftest import AUTH

RANGE = {"start_time": "2026-07-02T00:00:00Z", "end_time": "2026-09-30T00:00:00Z"}


def test_health_is_public(sim_client):
    r = sim_client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_missing_and_invalid_token_are_rejected_with_error_envelope(sim_client):
    r = sim_client.get("/assets/search", params={"query": "pump"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    r = sim_client.get("/assets/search", params={"query": "pump"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_trace_headers_are_echoed_and_logged(sim_client, sim_app):
    headers = {**AUTH, "trace_id": "trace-abc", "x-client-id": "tester", "x-metadata-tag": "unit"}
    r = sim_client.post(
        "/alarms/summary",
        headers=headers,
        json={"asset_ids": ["BFP-101"], "time_range": RANGE, "group_by": ["alarm_name"], "kpis": ["alarm_count"]},
    )
    assert r.status_code == 200
    assert r.headers["trace_id"] == "trace-abc" and r.headers["x-client-id"] == "tester"
    assert r.json()["meta"]["trace_id"] == "trace-abc"
    assert any(e["trace_id"] == "trace-abc" and e["metadata_tag"] == "unit" for e in sim_app.state.request_log)


def test_trace_id_generated_when_absent(sim_client):
    r = sim_client.get("/assets/search", params={"query": "pump"}, headers=AUTH)
    assert r.headers["trace_id"].startswith("sim-")


def test_asset_search_ranks_exact_name_first(sim_client):
    body = sim_client.get("/assets/search", params={"query": "Boiler Feed Pump 101", "limit": 5}, headers=AUTH).json()
    assert body["results"][0]["asset_id"] == "BFP-101"
    assert body["results"][0]["exact_match"] is True


def test_asset_search_by_class_and_unit(sim_client):
    body = sim_client.get("/assets/search", params={"query": "motor", "unit": "Unit 5"}, headers=AUTH).json()
    assert [r["asset_id"] for r in body["results"][:3]] == ["M-501", "M-502", "M-503"]


def test_metadata_includes_related_assets(sim_client):
    body = sim_client.get("/assets/BFP-101/metadata", headers=AUTH).json()
    related = {r["asset_id"]: r["relationship"] for r in body["related_assets"]}
    assert related["DA-101"] == "suction_source" and related["M-101"] == "driver"


def test_unknown_asset_returns_404_envelope(sim_client):
    r = sim_client.get("/assets/NOPE-999/metadata", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_alarm_pagination(sim_client):
    first = sim_client.get("/alarms", params={"site": "EastRefinery", "page": 1, "page_size": 10}, headers=AUTH).json()
    second = sim_client.get("/alarms", params={"site": "EastRefinery", "page": 2, "page_size": 10}, headers=AUTH).json()
    assert len(first["data"]) == 10 and first["pagination"]["has_next"] is True
    assert first["pagination"]["total_items"] > 20
    assert not {a["alarm_id"] for a in first["data"]} & {a["alarm_id"] for a in second["data"]}


def test_page_size_limit_is_validated(sim_client):
    r = sim_client.get("/alarms", params={"site": "EastRefinery", "page_size": 1000}, headers=AUTH)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_body_returns_validation_error(sim_client):
    r = sim_client.post(
        "/alarms/summary", headers=AUTH, json={"time_range": {"start_time": "2026-09-01T00:00:00Z", "end_time": "2026-08-01T00:00:00Z"}}
    )
    assert r.status_code == 422
    r = sim_client.post("/alarms/summary", headers=AUTH, json={"time_range": RANGE, "kpis": ["not_a_kpi"]})
    assert r.status_code == 422


def test_active_critical_alarm_on_bfp102(sim_client):
    rows = sim_client.get("/alarms", params={"asset_id": "BFP-102", "status": "active"}, headers=AUTH).json()["data"]
    assert {"BFP-SUCT-P-LL", "BFP-VIB-HH"} <= {a["alarm_code"] for a in rows}
    assert any(a["severity"] == "critical" and not a["acknowledged"] for a in rows)


def test_correlation_finds_deaerator_as_common_cause(sim_client):
    body = sim_client.post(
        "/alarms/correlation", headers=AUTH, json={"asset_ids": ["BFP-101"], "time_range": RANGE, "severity_threshold": "medium"}
    ).json()
    assert body["common_cause_candidates"][0]["asset_id"] == "DA-101"
    assert any("DA-101 DA-LVL-L" in i for i in body["insights"])


def test_priority_score_ranks_surge_highest_in_east_refinery(sim_client):
    active = sim_client.get("/alarms", params={"site": "EastRefinery", "status": "active"}, headers=AUTH).json()["data"]
    scores = {
        a["alarm_code"]: sim_client.post("/alarms/priority-score", headers=AUTH, json={"alarm_id": a["alarm_id"]}).json() for a in active
    }
    best = max(scores.values(), key=lambda s: s["priority_score"])
    assert best["alarm_code"] == "CMP-SURGE" and best["priority_band"] == "urgent"
    assert sum(c["weight_pct"] for c in best["components"]) == 100


def test_flood_analysis_detects_unit2_flood(sim_client):
    body = sim_client.post(
        "/alarms/flood-analysis",
        headers=AUTH,
        json={"unit": "Unit 2", "time_range": {"start_time": "2026-05-01T00:00:00Z", "end_time": "2026-07-01T00:00:00Z"}},
    ).json()
    assert body["flood_count"] >= 1
    assert body["flood_windows"][0]["alarm_count"] > 10


def test_recommendations_include_unsafe_restart_for_vibration_trip(sim_client):
    alarm = sim_client.get("/alarms", params={"asset_id": "BFP-102", "alarm_code": "BFP-VIB-HH", "status": "active"}, headers=AUTH).json()[
        "data"
    ][0]
    body = sim_client.post(
        "/recommendations/operator-actions",
        headers=AUTH,
        json={"alarm_id": alarm["alarm_id"], "include_related": True, "include_historical_pattern": True},
    ).json()
    assert any("restart" in r["action"].lower() for r in body["recommendations"])
    assert "historical_pattern" in body and "related_alarms" in body


def test_calculation_generate_execute_chain(sim_client):
    filters = {"unit": "Unit 4", **RANGE}
    gen = sim_client.post(
        "/calculation-code/generate", headers=AUTH, json={"calculation_type": "nuisance_alarm_score", "filters": filters}
    ).json()
    out = sim_client.post(
        "/calculation-code/execute", headers=AUTH, json={"calculation_id": gen["calculation_id"], "filters": filters}
    ).json()
    assert out["result"]["unit"] == "score" and out["result"]["value"] > 0
    r = sim_client.post("/calculation-code/execute", headers=AUTH, json={"calculation_id": "CALC-NOPE"})
    assert r.status_code == 404


def test_fault_injection_returns_configured_errors(sim_client):
    sim_client.post("/admin/faults", headers=AUTH, json={"path_prefix": "/assets/search", "mode": "rate_limit", "count": 1})
    r = sim_client.get("/assets/search", params={"query": "pump"}, headers=AUTH)
    assert r.status_code == 429 and r.headers["Retry-After"] == "1"
    assert sim_client.get("/assets/search", params={"query": "pump"}, headers=AUTH).status_code == 200


def test_seed_data_is_deterministic(sim_settings):
    from alarm_api_sim.seed import generate_alarms

    a = generate_alarms(sim_settings.anchor_time, 42)
    b = generate_alarms(sim_settings.anchor_time, 42)
    assert [(x.alarm_id, x.alarm_code, x.start_time) for x in a] == [(x.alarm_id, x.alarm_code, x.start_time) for x in b]
