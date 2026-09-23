"""
Copilot orchestration layer — the combined MCP + RAG workflow.

``handle_query`` is the single entry point used by the FastAPI backend (and
directly by tests): it runs intent/entity extraction, plans and executes a
multi-step MCP tool chain against the Alarm Management API (asset resolution
-> alarms -> correlation/priority -> recommendations, depending on intent),
retrieves grounding document passages through RAG, and produces a single
grounded answer with citations and a full MCP execution trace. MCP and RAG
run as one combined workflow here, not as two unrelated demos bolted
together — every answer draws on both.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.backend.copilot.nlu import Intent, NLUResult, analyze
from apps.backend.copilot.prompting import SYSTEM_PROMPT, build_user_prompt
from apps.backend.copilot.synthesis import Findings, synthesize_template
from apps.backend.llm.provider import LLMProvider
from apps.backend.mcp_client.client import MCPCallResult, MCPClient
from rag.retrieval.retriever import Retriever

logger = logging.getLogger("copilot_orchestrator")


@dataclass
class CopilotResponse:
    query: str
    intent: str
    answer: str
    findings: dict[str, Any]
    mcp_trace: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    low_confidence_retrieval: bool = False
    llm_provider_used: str = "template"
    warnings: list[str] = field(default_factory=list)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _window(days_back: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    return _iso(start), _iso(end)


class CopilotOrchestrator:
    def __init__(self, mcp_client: MCPClient, retriever: Retriever, llm_provider: LLMProvider):
        self.mcp_client = mcp_client
        self.retriever = retriever
        self.llm_provider = llm_provider

    async def handle_query(self, query: str) -> CopilotResponse:
        nlu: NLUResult = analyze(query)
        trace: list[MCPCallResult] = []
        warnings: list[str] = []
        findings = Findings()

        asset = await self._resolve_asset(nlu, trace, warnings)
        if asset:
            findings.asset = asset

        # An asset was explicitly named in the question and didn't resolve — stop
        # here. Running the planners, RAG retrieval, and synthesis anyway just
        # surfaces an empty/unrelated answer (generic procedure citations, "no
        # data retrieved" placeholders) under a "no asset found" warning, which
        # reads as broken rather than as a clean degraded-scenario response.
        asset_named_but_unresolved = bool(nlu.entities.asset_phrase) and asset is None
        if asset_named_but_unresolved:
            return CopilotResponse(
                query=query,
                intent=nlu.intent.value,
                answer=" ".join(warnings) or "No matching asset found for this question.",
                findings=_findings_to_dict(findings),
                mcp_trace=[c.to_trace_entry() for c in trace],
                citations=[],
                low_confidence_retrieval=False,
                llm_provider_used="template",
                warnings=warnings,
            )

        if nlu.intent == Intent.ACTIVE_ALARMS:
            await self._plan_active_alarms(nlu, asset, findings, trace, warnings)
        elif nlu.intent == Intent.RECURRING_INVESTIGATION:
            await self._plan_recurring_investigation(nlu, asset, findings, trace, warnings)
        elif nlu.intent == Intent.HIGHEST_PRIORITY:
            await self._plan_highest_priority(nlu, asset, findings, trace, warnings)
        elif nlu.intent in (Intent.RELATED_ASSETS, Intent.PROCEDURE_LOOKUP, Intent.RECOMMENDATION_CONSISTENCY):
            await self._plan_alarm_centric(nlu, asset, findings, trace, warnings)
        else:  # FULL_INVESTIGATION — broad, multi-tool investigation when intent is ambiguous
            await self._plan_full_investigation(nlu, asset, findings, trace, warnings)

        rag_query = self._build_rag_query(nlu, findings)
        asset_names = [asset["name"]] if asset else ([nlu.entities.asset_phrase] if nlu.entities.asset_phrase else None)
        rag_results = self.retriever.retrieve(rag_query, asset_names=asset_names, top_k=4)
        low_confidence = self.retriever.is_low_confidence(rag_results)
        rag_chunks = [r.to_dict() for r in rag_results]

        answer, provider_used = await self._synthesize(query, findings, rag_chunks)

        return CopilotResponse(
            query=query,
            intent=nlu.intent.value,
            answer=answer,
            findings=_findings_to_dict(findings),
            mcp_trace=[c.to_trace_entry() for c in trace],
            citations=rag_chunks,
            low_confidence_retrieval=low_confidence,
            llm_provider_used=provider_used,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Planning steps
    # ------------------------------------------------------------------

    async def _call(self, trace: list[MCPCallResult], tool: str, args: dict) -> MCPCallResult:
        result = await self.mcp_client.call_tool(tool, args)
        trace.append(result)
        return result

    async def _resolve_asset(self, nlu: NLUResult, trace: list[MCPCallResult], warnings: list[str]) -> dict | None:
        phrase = nlu.entities.asset_phrase
        if not phrase:
            return None
        result = await self._call(
            trace,
            "search_assets",
            {"query": phrase, "limit": 5, **({"unit": nlu.entities.unit} if nlu.entities.unit else {})},
        )
        if not result.ok:
            warnings.append(f"Asset resolution failed for '{phrase}': {result.error}")
            return None
        results = (result.result or {}).get("results", [])
        if not results:
            warnings.append(f"No asset found matching '{phrase}'.")
            return None
        if len(results) > 1:
            warnings.append(
                f"'{phrase}' matched {len(results)} assets; using the closest match "
                f"({results[0]['name']}). Ask a more specific question to disambiguate."
            )
        return results[0]

    async def _latest_alarm(
        self, asset_id: str, trace: list[MCPCallResult], *, status: str | None = None
    ) -> dict | None:
        result = await self._call(
            trace,
            "get_alarms",
            {"asset_id": asset_id, "page": 1, "page_size": 1, **({"status": status} if status else {})},
        )
        if result.ok and result.result.get("data"):
            return result.result["data"][0]
        if status:
            return await self._latest_alarm(asset_id, trace, status=None)
        return None

    async def _plan_active_alarms(self, nlu, asset, findings: Findings, trace, warnings):
        if nlu.entities.asset_phrase and not asset:
            # An asset was explicitly named but didn't resolve — the warning from
            # _resolve_asset already explains why; don't silently fall back to an
            # unfiltered, plant-wide alarm list here.
            return
        args: dict[str, Any] = {"status": "active", "page": 1, "page_size": 50}
        if asset:
            args["asset_id"] = asset["asset_id"]
        elif nlu.entities.unit:
            args["unit"] = nlu.entities.unit
        elif nlu.entities.site:
            args["site"] = nlu.entities.site
        result = await self._call(trace, "get_alarms", args)
        if not result.ok:
            warnings.append(f"Could not retrieve active alarms: {result.error}")
            return
        alarms = result.result.get("data", [])
        if nlu.entities.severities:
            alarms = [a for a in alarms if a["severity"] in nlu.entities.severities]
        findings.alarms = alarms
        if alarms:
            top = max(alarms, key=lambda a: {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(a["severity"], 0))
            findings.top_alarm = top
            rec_result = await self._call(trace, "get_operator_recommendations", {"alarm_id": top["alarm_id"]})
            if rec_result.ok:
                findings.recommendations = rec_result.result

    async def _plan_recurring_investigation(self, nlu, asset, findings: Findings, trace, warnings):
        if not asset:
            warnings.append("Could not resolve an asset for the recurrence investigation.")
            return
        start, end = _window(nlu.entities.days_back)
        summary_result = await self._call(
            trace,
            "get_alarm_summary",
            {
                "asset_ids": [asset["asset_id"]],
                "start_time": start,
                "end_time": end,
                "severity": nlu.entities.severities or None,
            },
        )
        if summary_result.ok:
            findings.summary = summary_result.result

        corr_result = await self._call(
            trace,
            "get_alarm_correlation",
            {
                "asset_ids": [asset["asset_id"]],
                "start_time": start,
                "end_time": end,
            },
        )
        if corr_result.ok:
            findings.correlation = corr_result.result

        # Recommendations should be for the alarm that is actually recurring (the top
        # group from the summary above), not just whatever alarm happened most recently —
        # otherwise the answer can cite one alarm's stats while recommending for another.
        top_alarm_name = None
        if findings.summary and findings.summary.get("summary"):
            top_alarm_name = findings.summary["summary"][0]["group_key"]

        alarms_result = await self._call(
            trace,
            "get_alarms",
            {
                "asset_id": asset["asset_id"],
                "start_time": start,
                "end_time": end,
                "page_size": 100,
            },
        )
        candidate_alarms = alarms_result.result.get("data", []) if alarms_result.ok else []
        findings.alarms = candidate_alarms

        top_alarm = None
        if top_alarm_name:
            matching = [a for a in candidate_alarms if a["alarm_name"] == top_alarm_name]
            top_alarm = matching[0] if matching else None
        if not top_alarm:
            top_alarm = await self._latest_alarm(asset["asset_id"], trace)
        if top_alarm:
            findings.top_alarm = top_alarm
            rec_result = await self._call(trace, "get_operator_recommendations", {"alarm_id": top_alarm["alarm_id"]})
            if rec_result.ok:
                findings.recommendations = rec_result.result

    async def _plan_highest_priority(self, nlu, asset, findings: Findings, trace, warnings):
        if nlu.entities.asset_phrase and not asset:
            # Same reasoning as _plan_active_alarms: an asset was named but didn't
            # resolve, so don't silently fall back to plant-wide priority scoring.
            return
        args: dict[str, Any] = {"status": "active", "page": 1, "page_size": 50}
        if asset:
            args["asset_id"] = asset["asset_id"]
        elif nlu.entities.unit:
            args["unit"] = nlu.entities.unit
        elif nlu.entities.site:
            args["site"] = nlu.entities.site
        alarms_result = await self._call(trace, "get_alarms", args)
        if not alarms_result.ok:
            warnings.append(f"Could not retrieve alarms: {alarms_result.error}")
            return
        alarms = alarms_result.result.get("data", [])
        findings.alarms = alarms
        if not alarms:
            warnings.append("No active alarms found to score for priority.")
            return

        scored = []
        for al in alarms[:15]:  # bounded fan-out
            score_result = await self._call(trace, "get_priority_score", {"alarm_id": al["alarm_id"]})
            if score_result.ok:
                scored.append((al, score_result.result))
        if not scored:
            return
        top_alarm, top_score = max(scored, key=lambda pair: pair[1]["priority_score"])
        findings.top_alarm = top_alarm
        findings.priority = top_score
        rec_result = await self._call(trace, "get_operator_recommendations", {"alarm_id": top_alarm["alarm_id"]})
        if rec_result.ok:
            findings.recommendations = rec_result.result

    async def _plan_alarm_centric(self, nlu, asset, findings: Findings, trace, warnings):
        """Shared plan for RELATED_ASSETS / PROCEDURE_LOOKUP / RECOMMENDATION_CONSISTENCY —
        all three need: resolve asset -> most relevant alarm -> operator recommendations."""
        if not asset:
            warnings.append("Could not resolve an asset for this question.")
            return
        alarm = await self._latest_alarm(asset["asset_id"], trace, status="active")
        if not alarm:
            warnings.append(f"No alarm history found for {asset['name']}.")
            return
        findings.top_alarm = alarm
        rec_result = await self._call(trace, "get_operator_recommendations", {"alarm_id": alarm["alarm_id"]})
        if rec_result.ok:
            findings.recommendations = rec_result.result

    async def _plan_full_investigation(self, nlu, asset, findings: Findings, trace, warnings):
        if not asset:
            warnings.append("Could not resolve an asset for this investigation.")
            return
        start, end = _window(nlu.entities.days_back)

        alarms_result = await self._call(
            trace,
            "get_alarms",
            {
                "asset_id": asset["asset_id"],
                "start_time": start,
                "end_time": end,
                "page_size": 100,
            },
        )
        if alarms_result.ok:
            findings.alarms = alarms_result.result.get("data", [])

        summary_result = await self._call(
            trace,
            "get_alarm_summary",
            {
                "asset_ids": [asset["asset_id"]],
                "start_time": start,
                "end_time": end,
                "severity": nlu.entities.severities or ["high", "critical"],
            },
        )
        if summary_result.ok:
            findings.summary = summary_result.result

        corr_result = await self._call(
            trace,
            "get_alarm_correlation",
            {
                "asset_ids": [asset["asset_id"]],
                "start_time": start,
                "end_time": end,
            },
        )
        if corr_result.ok:
            findings.correlation = corr_result.result

        candidate_alarm = None
        if findings.alarms:
            active = [a for a in findings.alarms if a["status"] == "active"]
            pool = active or findings.alarms
            severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            candidate_alarm = max(pool, key=lambda a: severity_rank.get(a["severity"], 0))
        if not candidate_alarm:
            candidate_alarm = await self._latest_alarm(asset["asset_id"], trace)
        if candidate_alarm:
            findings.top_alarm = candidate_alarm
            score_result = await self._call(trace, "get_priority_score", {"alarm_id": candidate_alarm["alarm_id"]})
            if score_result.ok:
                findings.priority = score_result.result
            rec_result = await self._call(
                trace, "get_operator_recommendations", {"alarm_id": candidate_alarm["alarm_id"]}
            )
            if rec_result.ok:
                findings.recommendations = rec_result.result

    # ------------------------------------------------------------------
    # RAG query construction + answer synthesis
    # ------------------------------------------------------------------

    @staticmethod
    def _build_rag_query(nlu: NLUResult, findings: Findings) -> str:
        parts = [nlu.raw_query]
        if findings.top_alarm:
            parts.append(findings.top_alarm.get("alarm_name", ""))
        if findings.asset:
            parts.append(findings.asset.get("name", ""))
            parts.append(findings.asset.get("asset_type", ""))
        return " ".join(p for p in parts if p)

    async def _synthesize(self, query: str, findings: Findings, rag_chunks: list[dict]) -> tuple[str, str]:
        template_answer = synthesize_template(query, findings, rag_chunks)

        if self.llm_provider.name == "template":
            return template_answer, "template"

        api_blocks: list[tuple[str, dict]] = []
        fd = _findings_to_dict(findings)
        for key, value in fd.items():
            if value:
                api_blocks.append((key, value))

        user_prompt = build_user_prompt(query, api_blocks, rag_chunks)
        llm_answer = await self.llm_provider.complete(SYSTEM_PROMPT, user_prompt)
        if llm_answer.strip():
            return llm_answer.strip(), self.llm_provider.name
        logger.warning(
            "LLM provider '%s' returned no output; falling back to template synthesis", self.llm_provider.name
        )
        return template_answer, "template (llm fallback)"


def _findings_to_dict(findings: Findings) -> dict[str, Any]:
    return {
        "asset": findings.asset,
        "alarms": findings.alarms,
        "summary": findings.summary,
        "correlation": findings.correlation,
        "priority": findings.priority,
        "top_alarm": findings.top_alarm,
        "recommendations": findings.recommendations,
    }