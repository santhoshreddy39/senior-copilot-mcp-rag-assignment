"""
Copilot backend — FastAPI application that wires together the MCP client, the
RAG retriever, and the pluggable LLM provider behind a small HTTP API the GUI
(apps/frontend) talks to.

This process is the copilot's orchestration layer: it never calls the Alarm
Management API directly (see connectors/alarm_api_client.py's module
docstring) — all Alarm Management API access goes through the MCP client ->
MCP server -> connector chain, so the tool trace shown in the GUI is
complete rather than a partial picture of what actually happened.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv()  # no-op if .env is absent (e.g. docker-compose already injected env vars)

from apps.backend.config import get_settings  # noqa: E402
from apps.backend.copilot.orchestrator import CopilotOrchestrator  # noqa: E402
from apps.backend.llm.provider import get_llm_provider  # noqa: E402
from apps.backend.mcp_client.client import MCPClient  # noqa: E402
from rag.retrieval.retriever import Retriever  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("copilot_backend")

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    mcp_env = {
        **os.environ,
        "ALARM_API_BASE_URL": settings.alarm_api_base_url,
        "ALARM_API_TOKEN": settings.alarm_api_token,
    }
    mcp_client = MCPClient(env=mcp_env)
    await mcp_client.connect()

    retriever = Retriever()
    llm_provider = get_llm_provider()
    orchestrator = CopilotOrchestrator(mcp_client=mcp_client, retriever=retriever, llm_provider=llm_provider)

    _state["mcp_client"] = mcp_client
    _state["orchestrator"] = orchestrator
    logger.info(
        "copilot_backend ready llm_provider=%s mcp_tools=%s",
        llm_provider.name,
        [t.name for t in mcp_client.available_tools],
    )
    try:
        yield
    finally:
        await mcp_client.close()


app = FastAPI(title="Alarm Investigation Copilot", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    query: str


@app.get("/health")
async def health():
    mcp_client: MCPClient = _state.get("mcp_client")
    return {
        "status": "ok",
        "mcp_connected": mcp_client is not None,
        "mcp_tool_count": len(mcp_client.available_tools) if mcp_client else 0,
        "llm_provider": _state["orchestrator"].llm_provider.name if "orchestrator" in _state else None,
    }


@app.get("/mcp/tools")
async def list_mcp_tools():
    mcp_client: MCPClient = _state["mcp_client"]
    return {"tools": [asdict_tool(t) for t in mcp_client.available_tools]}


def asdict_tool(tool) -> dict:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}


@app.post("/chat")
async def chat(request: ChatRequest):
    orchestrator: CopilotOrchestrator = _state["orchestrator"]
    response = await orchestrator.handle_query(request.query)
    return asdict(response)
