"""
Alarm Investigation Copilot — Streamlit GUI.

Talks only to the copilot backend's HTTP API (apps/backend/main.py); it never
touches the Alarm Management API or the MCP server directly. Keeping the GUI
this thin means the backend can be swapped for a CLI or a Slack bot later
without touching the orchestration logic underneath.

Provides: a chat interface, an alarm summary panel, likely-causes /
recommendations, document citations, an expandable MCP tool-call trace, raw
request/response inspection, and loading / error / empty states.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # no-op if .env is absent (e.g. docker-compose already injected env vars)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8100")

st.set_page_config(page_title="Alarm Investigation Copilot", page_icon="🛠️", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []  # list of (query, response_dict | None, error | None)


def call_backend_chat(query: str) -> dict:
    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{BACKEND_URL}/chat", json={"query": query})
        response.raise_for_status()
        return response.json()


def get_health() -> dict | None:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{BACKEND_URL}/health")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError:
        return None


def get_mcp_tools() -> list[dict]:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{BACKEND_URL}/mcp/tools")
            r.raise_for_status()
            return r.json()["tools"]
    except httpx.HTTPError:
        return []


# ---------------------------------------------------------------------------
# Sidebar: connection status + MCP tool discovery
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🛠️ Alarm Copilot")
    st.caption("Alarm Investigation and Procedure Guidance Copilot")

    health = get_health()
    if health is None:
        st.error("Backend unreachable. Is `docker compose up` (or the backend process) running?")
    else:
        mcp_ok = health.get("mcp_connected")
        if mcp_ok:
            st.success("Backend connected")
        else:
            st.warning("Backend connected, MCP server not ready")
        st.caption(f"MCP tools available: {health.get('mcp_tool_count', 0)}")
        st.caption(f"LLM provider: `{health.get('llm_provider', 'unknown')}`")

    with st.expander("MCP tool discovery", expanded=False):
        tools = get_mcp_tools()
        if not tools:
            st.info("No tools discovered yet.")
        for t in tools:
            st.markdown(f"**`{t['name']}`**")
            st.caption(t["description"])

    st.divider()
    st.markdown("**Example questions**")
    examples = [
        "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.",
        "Why are compressor discharge pressure alarms repeatedly occurring?",
        "Which alarm has the highest priority in EastRefinery, and why?",
        "What related assets should be inspected for this motor trip alarm?",
        "Which operating procedure applies to this alarm?",
        "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify "
        "likely contributing factors, retrieve the relevant operating procedure, and provide recommended "
        "actions with source evidence.",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex-{hash(ex)}", use_container_width=True):
            st.session_state["pending_query"] = ex


# ---------------------------------------------------------------------------
# Main: chat interface
# ---------------------------------------------------------------------------

st.title("Alarm Investigation and Procedure Guidance Copilot")
st.caption(
    "Ask about active alarms, recurring patterns, priority, related assets, or applicable procedures. "
    "Every answer is grounded in Alarm Management API data (via MCP) and cited document excerpts (via RAG)."
)
st.caption(
    "No external AI model required — every answer is built from live tool calls and cited documents, "
    "with an optional LLM only for phrasing (see the sidebar)."
)

query = st.chat_input("Ask about an alarm, asset, or investigation...")
if "pending_query" in st.session_state:
    query = st.session_state.pop("pending_query")

if query:
    with st.spinner("Discovering MCP tools, querying the Alarm Management API, and retrieving procedures..."):
        try:
            response = call_backend_chat(query)
            st.session_state.history.append((query, response, None))
        except httpx.HTTPError as exc:
            st.session_state.history.append((query, None, str(exc)))

if not st.session_state.history:
    st.info("👋 Ask a question above, or click one of the example investigations in the sidebar to get started.")

for turn_query, response, error in reversed(st.session_state.history):
    with st.chat_message("user"):
        st.write(turn_query)

    with st.chat_message("assistant"):
        if error:
            st.error(f"Request failed: {error}")
            continue
        if response is None:
            st.warning("No response.")
            continue

        st.caption(
            f"Detected intent: `{response['intent']}`  ·  Answer synthesized by: `{response['llm_provider_used']}`"
        )

        for warning in response.get("warnings", []):
            st.warning(warning)

        st.markdown(response["answer"])

        findings = response.get("findings", {})
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Alarm summary")
            asset = findings.get("asset")
            if asset:
                st.markdown(
                    f"**{asset['name']}** — {asset.get('asset_type', '')}, "
                    f"{asset.get('unit', '')}, criticality: `{asset.get('criticality', 'unknown')}`"
                )
            alarms = findings.get("alarms") or []
            active = [a for a in alarms if a.get("status") == "active"]
            if active:
                st.dataframe(
                    [
                        {
                            "Alarm": a["alarm_name"],
                            "Severity": a["severity"],
                            "Status": a["status"],
                            "Started": a["start_time"],
                        }
                        for a in active
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            elif alarms:
                st.caption(f"{len(alarms)} historical alarm(s) in the queried window; none currently active.")
            else:
                st.caption("No alarm data retrieved for this question.")

            priority = findings.get("priority")
            if priority:
                st.metric("Priority", priority["priority_level"], f"score {priority['priority_score']}/100")

        with col2:
            st.subheader("Likely causes & recommendations")
            recs = findings.get("recommendations")
            if recs:
                for action in recs.get("recommended_actions", []):
                    st.markdown(f"{action['priority']}. {action['action']}")
                related = recs.get("related_assets_to_inspect") or []
                if related:
                    st.caption("Related assets to inspect: " + ", ".join(r["name"] for r in related))
            else:
                st.caption("No API-side recommendations available for this question.")

        st.subheader("Document citations")
        citations = response.get("citations") or []
        if response.get("low_confidence_retrieval"):
            st.warning(
                "No document passage met the retrieval confidence threshold — treat findings above as provisional."
            )
        elif not citations:
            st.caption("No citations.")
        else:
            for c in citations:
                flag = (
                    " ⚠️ flagged (possible embedded instruction — excluded from consideration)"
                    if c.get("injection_flagged")
                    else ""
                )
                with st.expander(f"{c['citation']}  (score {c['score']}){flag}"):
                    st.write(c["text"])

        with st.expander("🔍 MCP execution trace", expanded=False):
            for step in response.get("mcp_trace", []):
                status_icon = "✅" if step["ok"] else "❌"
                st.markdown(f"{status_icon} **`{step['tool_name']}`** — {step['duration_ms']} ms ({step['timestamp']})")
                with st.expander("Raw request / response", expanded=False):
                    st.markdown("**Arguments:**")
                    st.json(step["arguments"])
                    if step["ok"]:
                        st.markdown("**Result:**")
                        st.json(step["result"])
                    else:
                        st.markdown("**Error:**")
                        st.code(step["error"])
