"""Centralized, environment-driven configuration. No secret ever has a real default.

Settings are read fresh on each ``get_settings()`` call (rather than baked in at
import time) so tests can set environment variables and see them take effect —
important because ``apps/backend/main.py``'s lifespan reads the Alarm Management
API location from here when spawning the MCP server subprocess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    alarm_api_base_url: str
    alarm_api_token: str
    mcp_server_script: str
    llm_provider: str
    document_path: str
    backend_host: str
    backend_port: int


def get_settings() -> Settings:
    return Settings(
        alarm_api_base_url=os.environ.get("ALARM_API_BASE_URL", "http://localhost:8000"),
        alarm_api_token=os.environ.get("ALARM_API_TOKEN", "demo-token"),
        mcp_server_script=os.environ.get("MCP_SERVER_SCRIPT", ""),
        llm_provider=os.environ.get("LLM_PROVIDER", ""),
        document_path=os.environ.get("DOCUMENT_PATH", "rag/documents"),
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8100")),
    )


# Convenience module-level accessor for callers that just want current values
# without importing get_settings() everywhere (e.g. simple scripts). Backend
# request-handling code should prefer calling get_settings() directly so it
# always reflects the current environment.
settings = get_settings()
