"""
MCP server tool tests: registration, discovery, schema validation, and each
tool's behaviour against a real (subprocess-hosted) Alarm Management API,
calling the tool functions directly (no MCP protocol framing) so failures
point straight at the business logic. tests/integration/test_mcp_client_server.py
covers the same server over the actual MCP stdio protocol.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SERVER_PATH = Path(__file__).resolve().parents[2] / "mcp-servers" / "alarm-management" / "server.py"


@pytest.fixture()
def server_module(live_simulator_url, monkeypatch):
    monkeypatch.setenv("ALARM_API_BASE_URL", live_simulator_url)
    monkeypatch.setenv("ALARM_API_TOKEN", "demo-token")
    spec = importlib.util.spec_from_file_location("alarm_mcp_server_test", SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod


async def test_tool_registration_and_discovery(server_module):
    tools = await server_module.mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "search_assets",
        "get_asset_metadata",
        "get_alarms",
        "get_alarm_by_id",
        "get_alarm_summary",
        "get_alarm_correlation",
        "get_priority_score",
        "get_operator_recommendations",
    }


async def test_tool_schemas_are_typed(server_module):
    tools = await server_module.mcp.list_tools()
    search_tool = next(t for t in tools if t.name == "search_assets")
    assert search_tool.inputSchema["properties"]["query"]["type"] == "string"
    assert search_tool.inputSchema["required"] == ["query"]


async def test_search_assets_resolves_known_asset(server_module):
    result = await server_module.search_assets(query="Compressor C-201")
    assert result["results"][0]["name"] == "Compressor C-201 Discharge"


async def test_input_validation_rejects_empty_query(server_module):
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        await server_module.search_assets(query="")


async def test_input_validation_rejects_bad_status(server_module):
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        await server_module.get_alarms(status="not-a-real-status")


async def test_not_found_is_mapped_to_tool_error_without_leaking_internals(server_module):
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError) as exc_info:
        await server_module.get_alarm_by_id(alarm_id="does-not-exist")
    assert "does-not-exist" in str(exc_info.value) or "Not found" in str(exc_info.value)
    assert "demo-token" not in str(exc_info.value)  # never leak the credential


async def test_auth_failure_is_mapped_to_tool_error(server_module, monkeypatch):
    from mcp.server.fastmcp.exceptions import ToolError

    monkeypatch.setenv("ALARM_API_TOKEN", "wrong-token")
    server_module._client = None  # force a fresh client to pick up the new token
    with pytest.raises(ToolError):
        await server_module.search_assets(query="pump")
    server_module._client = None
    monkeypatch.setenv("ALARM_API_TOKEN", "demo-token")


async def test_trace_id_is_propagated_when_provided(server_module):
    # No direct way to inspect the outbound header from here without a spy; this
    # confirms the call still succeeds end-to-end when an explicit trace_id is passed,
    # exercising the propagation code path (see connectors/alarm_api_client.py).
    result = await server_module.search_assets(query="pump", trace_id="trace-explicit-123")
    assert "results" in result


async def test_multi_step_chain_search_then_alarms_then_priority(server_module):
    search_result = await server_module.search_assets(query="Motor M-305")
    asset_id = search_result["results"][0]["asset_id"]
    alarms_result = await server_module.get_alarms(asset_id=asset_id, page_size=1)
    assert alarms_result["data"]
    alarm_id = alarms_result["data"][0]["alarm_id"]
    priority = await server_module.get_priority_score(alarm_id=alarm_id)
    assert 0 <= priority["priority_score"] <= 100

    await server_module.get_client().aclose()
