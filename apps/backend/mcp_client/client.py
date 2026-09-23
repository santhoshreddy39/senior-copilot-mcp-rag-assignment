"""
MCP client wrapper used by the copilot orchestration layer.

Connects to the candidate-developed Alarm Management MCP server over the
stdio transport (spawning it as a subprocess — the same mechanism Claude
Desktop and other MCP hosts use), performs tool discovery, and exposes a
single ``call_tool`` entry point that:

  * validates the requested tool exists (handles "unavailable tools")
  * records a structured trace entry for every call — timestamp, tool name,
    arguments, duration, status, and the raw request/response — which the
    GUI renders as the "expandable MCP tool-call trace" / "raw request and
    response inspection" panels
  * never raises on a tool-level failure; it returns a ``MCPCallResult`` with
    ``ok=False`` and an error message instead, so a multi-step chain can
    continue past a partial failure (per "Handling partial failures")

This is the ONLY place in the copilot that talks to the MCP server — the
orchestrator never imports the Alarm Management API connector directly.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger("mcp_client")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SERVER_SCRIPT = REPO_ROOT / "mcp-servers" / "alarm-management" / "server.py"


@dataclass
class MCPCallResult:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    ok: bool
    duration_ms: float
    result: Any = None
    error: str | None = None
    timestamp: str = ""

    def to_trace_entry(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """Owns one long-lived MCP session over stdio to the Alarm Management MCP server."""

    def __init__(self, server_script: Path | None = None, env: dict[str, str] | None = None):
        self._server_script = server_script or DEFAULT_SERVER_SCRIPT
        self._env = env
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools_by_name: dict[str, MCPToolInfo] = {}

    async def connect(self) -> None:
        self._exit_stack = AsyncExitStack()
        params = StdioServerParameters(command="python", args=[str(self._server_script)], env=self._env)
        read_stream, write_stream = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        self._session = session
        await self.discover_tools()
        logger.info("mcp_client connected server=%s tools=%s", self._server_script, list(self._tools_by_name.keys()))

    async def close(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
        self._session = None
        self._exit_stack = None

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # NOTE: connect()/close() must be awaited within the SAME asyncio task —
        # the underlying stdio transport uses an anyio TaskGroup whose cancel scope
        # is tied to the task that entered it. Using this class as an async context
        # manager (rather than connecting in a fixture and closing in a separate
        # teardown callback) keeps both calls in one task; see tests/integration
        # and tests/e2e for the pattern this project uses in pytest.
        await self.close()

    async def discover_tools(self) -> list[MCPToolInfo]:
        if not self._session:
            raise RuntimeError("MCPClient is not connected")
        result = await self._session.list_tools()
        self._tools_by_name = {
            t.name: MCPToolInfo(name=t.name, description=t.description or "", input_schema=t.inputSchema or {})
            for t in result.tools
        }
        return list(self._tools_by_name.values())

    @property
    def available_tools(self) -> list[MCPToolInfo]:
        return list(self._tools_by_name.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools_by_name

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPCallResult:
        call_id = f"call-{uuid.uuid4().hex[:10]}"
        started = time.time()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not self._session:
            return MCPCallResult(
                call_id,
                tool_name,
                arguments,
                ok=False,
                duration_ms=0.0,
                error="MCP client is not connected",
                timestamp=timestamp,
            )

        if tool_name not in self._tools_by_name:
            # Handling unavailable tools: fail this one call, do not crash the chain.
            return MCPCallResult(
                call_id,
                tool_name,
                arguments,
                ok=False,
                duration_ms=0.0,
                error=f"Tool '{tool_name}' is not available on this MCP server. "
                f"Available tools: {sorted(self._tools_by_name)}",
                timestamp=timestamp,
            )

        try:
            call_result = await self._session.call_tool(tool_name, arguments)
        except Exception as exc:  # transport-level failure (server crashed, pipe closed, etc.)
            duration_ms = round((time.time() - started) * 1000, 2)
            logger.exception("mcp_client transport_error tool=%s", tool_name)
            return MCPCallResult(
                call_id,
                tool_name,
                arguments,
                ok=False,
                duration_ms=duration_ms,
                error=f"MCP transport error: {exc}",
                timestamp=timestamp,
            )

        duration_ms = round((time.time() - started) * 1000, 2)

        if call_result.isError:
            error_text = _extract_text(call_result) or "Tool reported an error"
            logger.warning("mcp_client tool_error tool=%s error=%s", tool_name, error_text)
            return MCPCallResult(
                call_id, tool_name, arguments, ok=False, duration_ms=duration_ms, error=error_text, timestamp=timestamp
            )

        payload = _extract_structured(call_result)
        return MCPCallResult(
            call_id, tool_name, arguments, ok=True, duration_ms=duration_ms, result=payload, timestamp=timestamp
        )


def _extract_text(call_result) -> str:
    parts = []
    for block in call_result.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def _extract_structured(call_result) -> Any:
    if getattr(call_result, "structuredContent", None) is not None:
        return call_result.structuredContent
    text = _extract_text(call_result)
    import json

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
