"""
MCP client integration tests, over the real MCP stdio protocol: spawns the
actual alarm-management MCP server as a subprocess (the same way the copilot
backend does) and drives it through MCPClient. Covers server connectivity,
tool discovery, tool invocation, invalid arguments, missing tools, and
partial failure.

NOTE on structure: each test opens its own ``async with MCPClient(...) as
client:`` block rather than sharing a fixture that connects in setup and
closes in teardown. The MCP stdio transport's cancel scope must be entered
and exited in the same asyncio task, and pytest-asyncio runs fixture
setup/teardown as separate task steps — spanning connect()/close() across
that boundary raises "Attempted to exit cancel scope in a different task".
Keeping the whole lifecycle inside one test coroutine avoids that entirely.
"""

import os

from apps.backend.mcp_client.client import MCPClient


def _env(live_simulator_url: str) -> dict:
    return {**os.environ, "ALARM_API_BASE_URL": live_simulator_url, "ALARM_API_TOKEN": "demo-token"}


async def test_server_connectivity_and_tool_discovery(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as client:
        tools = client.available_tools
        assert len(tools) == 8
        assert client.has_tool("search_assets")
        assert not client.has_tool("delete_everything")


async def test_tool_invocation_success(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as client:
        result = await client.call_tool("search_assets", {"query": "Boiler Feed Pump 101"})
        assert result.ok
        assert result.result["results"][0]["asset_id"].startswith("AST-")
        assert result.duration_ms >= 0


async def test_invalid_arguments_are_handled_without_raising(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as client:
        result = await client.call_tool("get_alarms", {"status": "not-a-status"})
        assert result.ok is False
        assert "status" in result.error.lower()


async def test_missing_tool_is_handled_without_raising(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as client:
        result = await client.call_tool("this_tool_does_not_exist", {})
        assert result.ok is False
        assert "not available" in result.error


async def test_multi_step_chaining_output_of_one_call_feeds_the_next(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as client:
        r1 = await client.call_tool("search_assets", {"query": "Compressor C-201"})
        assert r1.ok
        asset_id = r1.result["results"][0]["asset_id"]

        r2 = await client.call_tool(
            "get_alarm_correlation",
            {
                "asset_ids": [asset_id],
                "start_time": "2026-01-01T00:00:00Z",
                "end_time": "2026-09-22T00:00:00Z",
            },
        )
        assert r2.ok
        assert "correlated_pairs" in r2.result


async def test_partial_failure_in_a_chain_does_not_abort_the_client(live_simulator_url):
    """One failing call in a sequence must not corrupt the client/session state —
    subsequent calls should still succeed."""
    async with MCPClient(env=_env(live_simulator_url)) as client:
        bad = await client.call_tool("get_asset_metadata", {"asset_id": "AST-9999"})
        assert bad.ok is False

        good = await client.call_tool("search_assets", {"query": "pump"})
        assert good.ok is True


async def test_trace_entries_carry_request_and_response_for_gui_inspection(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as client:
        result = await client.call_tool("search_assets", {"query": "pump"})
        entry = result.to_trace_entry()
        assert entry["arguments"] == {"query": "pump"}
        assert entry["result"] is not None
        assert entry["timestamp"]
