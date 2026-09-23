"""Shared pytest fixtures: an in-process ASGI transport for the simulator (fast,
no socket) and a real subprocess-hosted simulator for tests that need an actual
TCP server (MCP-over-stdio integration tests, since the MCP server subprocess
needs a real ALARM_API_BASE_URL it can reach)."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent


@pytest.fixture()
def simulator_transport(monkeypatch):
    monkeypatch.setenv("ALARM_API_TOKEN", "demo-token")
    from apps.backend.simulator.main import app as simulator_app

    return httpx.ASGITransport(app=simulator_app)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_simulator_url():
    """Starts the real Alarm Management API simulator as a subprocess on a free
    port, for tests that need a genuine TCP server (the MCP server subprocess
    connects over real HTTP, so it cannot use an in-process ASGI transport)."""
    port = _free_port()
    env = {"ALARM_API_TOKEN": "demo-token", "PATH": "/usr/bin:/bin"}
    import os

    env = {**os.environ, **env}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.backend.simulator.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO_ROOT),
        env=env,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                r = httpx.get(f"{base_url}/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            proc.terminate()
            raise RuntimeError("simulator subprocess did not become healthy in time")
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=5)
