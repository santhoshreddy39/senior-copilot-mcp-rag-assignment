"""
Orchestration tests: multi-step MCP chains, MCP output passed into subsequent
tools, RAG retrieval within the same workflow, combined answer generation,
and behaviour when an asset can't be resolved (partial-source failure /
conflicting evidence handling at the orchestration layer).

See tests/integration/test_mcp_client_server.py's module docstring for why
each test opens its own ``async with MCPClient(...)`` block instead of
sharing a connect-in-setup / close-in-teardown fixture.
"""

import os

from apps.backend.copilot.orchestrator import CopilotOrchestrator
from apps.backend.llm.provider import TemplateProvider
from apps.backend.mcp_client.client import MCPClient
from rag.retrieval.retriever import Retriever


def _env(live_simulator_url: str) -> dict:
    return {**os.environ, "ALARM_API_BASE_URL": live_simulator_url, "ALARM_API_TOKEN": "demo-token"}


async def test_active_alarms_query_chains_search_alarms_and_recommendations(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as mcp_client:
        orch = CopilotOrchestrator(mcp_client=mcp_client, retriever=Retriever(), llm_provider=TemplateProvider())
        response = await orch.handle_query(
            "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions."
        )
        tool_sequence = [c["tool_name"] for c in response.mcp_trace]
        assert tool_sequence[0] == "search_assets"
        assert "get_alarms" in tool_sequence
        assert response.findings["asset"]["name"] == "Boiler Feed Pump 102"
        assert "Recommended immediate actions" in response.answer or response.findings["recommendations"]


async def test_highest_priority_query_scores_every_active_alarm(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as mcp_client:
        orch = CopilotOrchestrator(mcp_client=mcp_client, retriever=Retriever(), llm_provider=TemplateProvider())
        response = await orch.handle_query("Which alarm has the highest priority in EastRefinery, and why?")
        tool_sequence = [c["tool_name"] for c in response.mcp_trace]
        assert tool_sequence.count("get_priority_score") >= 1
        assert response.findings["priority"] is not None
        assert response.findings["priority"]["priority_level"] in ("P1", "P2", "P3", "P4")


async def test_recurring_investigation_combines_summary_correlation_and_rag(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as mcp_client:
        orch = CopilotOrchestrator(mcp_client=mcp_client, retriever=Retriever(), llm_provider=TemplateProvider())
        response = await orch.handle_query("Why are compressor discharge pressure alarms repeatedly occurring?")
        tool_sequence = [c["tool_name"] for c in response.mcp_trace]
        assert "get_alarm_summary" in tool_sequence
        assert "get_alarm_correlation" in tool_sequence
        assert response.citations, "recurring-alarm investigation must be grounded in retrieved documents"
        assert any(
            "compressor" in c["citation"].lower() or "discharge" in c["citation"].lower() for c in response.citations
        )


async def test_full_recurring_investigation_scenario_end_to_end(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as mcp_client:
        orch = CopilotOrchestrator(mcp_client=mcp_client, retriever=Retriever(), llm_provider=TemplateProvider())
        response = await orch.handle_query(
            "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, "
            "identify likely contributing factors, retrieve the relevant operating procedure, and provide "
            "recommended actions with source evidence."
        )
        # 1. Asset resolution through an MCP tool
        assert response.mcp_trace[0]["tool_name"] == "search_assets"
        assert response.findings["asset"]["name"] == "Boiler Feed Pump 101"
        # 2. Multi-step Alarm Management API chaining through MCP
        tool_sequence = [c["tool_name"] for c in response.mcp_trace]
        assert len(tool_sequence) >= 4
        assert all(c["ok"] for c in response.mcp_trace)
        # 3. Document retrieval through RAG + citations
        assert response.citations
        assert not response.low_confidence_retrieval
        # 4. Combined reasoning / recommendations present
        assert response.findings["recommendations"] is not None
        # 5. GUI-consumable execution trace
        assert all("duration_ms" in c for c in response.mcp_trace)


async def test_unresolvable_asset_produces_a_warning_not_a_crash(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as mcp_client:
        orch = CopilotOrchestrator(mcp_client=mcp_client, retriever=Retriever(), llm_provider=TemplateProvider())
        response = await orch.handle_query(
            "Show active alarms for the Zzyzx Nonexistent Turbine 999 and recommend actions."
        )
        assert response.warnings
        assert "No asset found" in response.warnings[0]
        assert response.answer


async def test_prompt_injection_content_never_leaks_into_the_answer(live_simulator_url):
    async with MCPClient(env=_env(live_simulator_url)) as mcp_client:
        orch = CopilotOrchestrator(mcp_client=mcp_client, retriever=Retriever(), llm_provider=TemplateProvider())
        response = await orch.handle_query(
            "Summarize the vendor email ticket note about an administrator reset for Boiler Feed Pump 102."
        )
        assert "ALARM_API_TOKEN" not in response.answer
        assert "demo-token" not in response.answer
