"""Integration tests for the Alarm Management API simulator's HTTP surface:
auth enforcement, pagination, trace header propagation, and the full
search -> metadata -> alarms -> alarm-detail chain used by the Postman
reference collections."""

import httpx
import pytest


@pytest.fixture()
async def http_client(simulator_transport):
    async with httpx.AsyncClient(transport=simulator_transport, base_url="http://testserver") as c:
        yield c


AUTH = {"Authorization": "Bearer demo-token"}


async def test_health_requires_no_auth(http_client):
    r = await http_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_missing_bearer_token_is_401(http_client):
    r = await http_client.get("/assets/search", params={"query": "pump"})
    assert r.status_code == 401


async def test_invalid_bearer_token_is_401(http_client):
    r = await http_client.get("/assets/search", params={"query": "pump"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_search_metadata_alarms_alarm_detail_chain(http_client):
    r1 = await http_client.get("/assets/search", params={"query": "Boiler Feed Pump 101"}, headers=AUTH)
    assert r1.status_code == 200
    asset_id = r1.json()["results"][0]["asset_id"]

    r2 = await http_client.get(f"/assets/{asset_id}/metadata", headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["name"] == "Boiler Feed Pump 101"

    r3 = await http_client.get("/alarms", params={"asset_id": asset_id, "page_size": 5}, headers=AUTH)
    assert r3.status_code == 200
    body = r3.json()
    assert body["pagination"]["page_size"] == 5
    assert len(body["data"]) <= 5

    if body["data"]:
        alarm_id = body["data"][0]["alarm_id"]
        r4 = await http_client.get(f"/alarms/{alarm_id}", headers=AUTH)
        assert r4.status_code == 200
        assert r4.json()["alarm_id"] == alarm_id


async def test_unknown_asset_metadata_is_404(http_client):
    r = await http_client.get("/assets/AST-9999/metadata", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["error"]["status_code"] == 404


async def test_pagination_is_consistent_across_pages(http_client):
    r1 = await http_client.get("/alarms", params={"page": 1, "page_size": 10}, headers=AUTH)
    r2 = await http_client.get("/alarms", params={"page": 2, "page_size": 10}, headers=AUTH)
    ids_page1 = {a["alarm_id"] for a in r1.json()["data"]}
    ids_page2 = {a["alarm_id"] for a in r2.json()["data"]}
    assert ids_page1.isdisjoint(ids_page2)
    assert r1.json()["pagination"]["total_count"] == r2.json()["pagination"]["total_count"]


async def test_trace_headers_are_echoed_back(http_client):
    r = await http_client.get(
        "/assets/search", params={"query": "pump"}, headers={**AUTH, "trace_id": "trace-echo-test"}
    )
    assert r.headers.get("x-trace-id") == "trace-echo-test"


async def test_alarms_summary_requires_valid_time_range(http_client):
    r = await http_client.post(
        "/alarms/summary",
        headers=AUTH,
        json={
            "asset_ids": ["AST-1000"],
            "time_range": {"start_time": "bad", "end_time": "also-bad"},
        },
    )
    assert r.status_code == 400


async def test_flood_analysis_end_to_end(http_client):
    r = await http_client.post(
        "/alarms/flood-analysis",
        headers=AUTH,
        json={
            "unit": "Unit 2",
            "time_range": {"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-09-22T00:00:00Z"},
            "threshold_count": 5,
            "rolling_window_minutes": 30,
        },
    )
    assert r.status_code == 200
    assert "flood_windows" in r.json()


async def test_kpi_definitions(http_client):
    r = await http_client.get("/analytics/kpi-definitions", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()["kpis"]) > 0
