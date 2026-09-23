"""
The full-stack end-to-end test: a backend request drives the real FastAPI
app (apps/backend/main.py) through its actual startup lifecycle, which
spawns the real MCP server subprocess, which calls the real (subprocess
-hosted) Alarm Management API simulator, combined with real RAG retrieval
over the document corpus, producing a grounded response with citations and a
full MCP execution trace. Nothing here is mocked — this is the same request
path the GUI drives in production. Also covers one degraded/failure scenario
(an asset that doesn't exist), so the failure path gets the same end-to-end
coverage as the happy path.
"""

from starlette.testclient import TestClient


def _make_client(live_simulator_url, monkeypatch) -> TestClient:
    monkeypatch.setenv("ALARM_API_BASE_URL", live_simulator_url)
    monkeypatch.setenv("ALARM_API_TOKEN", "demo-token")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)  # deterministic template synthesis for this test
    from apps.backend.main import app

    return TestClient(app)


def test_health_reports_mcp_connected(live_simulator_url, monkeypatch):
    with _make_client(live_simulator_url, monkeypatch) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["mcp_connected"] is True
        assert body["mcp_tool_count"] == 8


def test_mcp_tools_endpoint_lists_typed_tools_for_gui_discovery_panel(live_simulator_url, monkeypatch):
    with _make_client(live_simulator_url, monkeypatch) as client:
        r = client.get("/mcp/tools")
        assert r.status_code == 200
        tools = r.json()["tools"]
        assert {"search_assets", "get_operator_recommendations"} <= {t["name"] for t in tools}
        assert all("input_schema" in t and "properties" in t["input_schema"] for t in tools)


def test_successful_end_to_end_combined_scenario(live_simulator_url, monkeypatch):
    """SUCCESS scenario (per docs/README demo evidence requirements)."""
    with _make_client(live_simulator_url, monkeypatch) as client:
        r = client.post(
            "/chat",
            json={
                "query": "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 "
                "days, identify likely contributing factors, retrieve the relevant operating procedure, "
                "and provide recommended actions with source evidence.",
            },
        )
        assert r.status_code == 200
        body = r.json()

        # MCP tool discovery + execution
        assert len(body["mcp_trace"]) >= 4
        assert body["mcp_trace"][0]["tool_name"] == "search_assets"
        assert all(step["ok"] for step in body["mcp_trace"])

        # Alarm Management API data reached the response
        assert body["findings"]["asset"]["name"] == "Boiler Feed Pump 101"

        # RAG citations
        assert body["citations"]
        assert all("citation" in c and "doc_id" in c for c in body["citations"])

        # Grounded answer referencing the retrieved material
        assert "OP-204" in body["answer"] or "Boiler Feed Pump" in body["answer"]
        assert body["low_confidence_retrieval"] is False


def test_degraded_scenario_unresolvable_asset_still_returns_200_with_warning(live_simulator_url, monkeypatch):
    """FAILURE / degraded scenario: an asset that does not exist must not 500 the
    request — the copilot should degrade gracefully and surface a warning."""
    with _make_client(live_simulator_url, monkeypatch) as client:
        r = client.post("/chat", json={"query": "Show active alarms for the Zzyzx Nonexistent Turbine 999."})
        assert r.status_code == 200
        body = r.json()
        assert body["warnings"]
        assert body["answer"]
