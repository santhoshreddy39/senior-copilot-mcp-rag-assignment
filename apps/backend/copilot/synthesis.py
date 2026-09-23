"""
Deterministic, offline template synthesizer.

Used whenever no LLM provider is configured (or a configured provider call
fails at request time — see llm/provider.py), so the copilot always returns a
grounded, cited answer rather than an error. It narrates whichever
``Findings`` fields the orchestrator populated for the detected intent, so it
is one generic narrator rather than one template per intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Findings:
    asset: dict | None = None
    alarms: list[dict] = field(default_factory=list)
    summary: dict | None = None
    correlation: dict | None = None
    priority: dict | None = None
    top_alarm: dict | None = None
    recommendations: dict | None = None


def synthesize_template(query: str, findings: Findings, rag_chunks: list[dict]) -> str:
    lines: list[str] = []

    if findings.asset:
        a = findings.asset
        lines.append(
            f"**Asset:** {a.get('name', a.get('asset_id'))} "
            f"({a.get('asset_type', 'unknown type')}, {a.get('unit', '')}, "
            f"criticality: {a.get('criticality', 'unknown')})."
        )

    if findings.alarms:
        active = [al for al in findings.alarms if al.get("status") == "active"]
        if active:
            lines.append(f"\n**Active alarms ({len(active)}):**")
            for al in active[:8]:
                lines.append(
                    f"- [{al['severity'].upper()}] {al['alarm_name']} on {al['asset_name']} "
                    f"(alarm_id={al['alarm_id']}, since {al['start_time']})"
                )
        else:
            lines.append(
                f"\nNo currently active alarms matched the request ({len(findings.alarms)} "
                f"historical alarm record(s) found in the queried window)."
            )

    if findings.summary and findings.summary.get("summary"):
        lines.append("\n**Recurrence summary (grouped):**")
        for row in findings.summary["summary"][:5]:
            recurring = " — recurring" if row.get("is_recurring") else ""
            lines.append(
                f"- {row['group_key']}: {row['alarm_count']} occurrence(s){recurring}, "
                f"avg ack delay {row.get('avg_ack_delay_minutes')} min"
            )

    if findings.correlation and findings.correlation.get("correlated_pairs"):
        lines.append("\n**Correlated alarm pairs (possible common root cause):**")
        for pair in findings.correlation["correlated_pairs"][:4]:
            lines.append(
                f"- {pair['alarm_name_a']} ↔ {pair['alarm_name_b']}: "
                f"co-occurred {pair['cooccurrence_count']}x, avg lag "
                f"{pair['avg_lag_minutes']} min (confidence {pair['confidence']})"
            )
        related = findings.correlation.get("related_assets") or []
        if related:
            lines.append("\n**Related assets with overlapping alarm activity:**")
            for ra in related[:4]:
                lines.append(f"- {ra['name']} ({ra['relationship']}, {ra['alarm_overlap_count']} overlapping alarms)")

    if findings.priority:
        p = findings.priority
        lines.append(
            f"\n**Priority:** {p['priority_level']} (score {p['priority_score']}/100) — "
            f"driven by severity ({p['factors']['severity_score']}), asset criticality "
            f"({p['factors']['asset_criticality_score']}), recurrence "
            f"({p['factors']['recurrence_score']}, {p['factors']['recurrence_count_90d']} occurrences "
            f"in the last 90 days), and current status ({p['factors']['status_score']})."
        )

    if findings.recommendations:
        r = findings.recommendations
        lines.append(f"\n**Recommended immediate actions for {r.get('alarm_name', 'this alarm')}:**")
        for action in r.get("recommended_actions", [])[:5]:
            lines.append(f"{action['priority']}. {action['action']}")
        related = r.get("related_assets_to_inspect") or []
        if related:
            lines.append("\n**Related assets to inspect:**")
            for ra in related:
                lines.append(f"- {ra['name']}")
        hist = r.get("historical_pattern")
        if hist:
            pattern = "a recurring pattern" if hist.get("is_recurring") else "an isolated occurrence"
            lines.append(
                f"\nThis alarm shows {pattern} ({hist.get('occurrence_count_90d')} occurrence(s) in the last 90 days)."
            )

    if rag_chunks:
        lines.append("\n**Relevant procedure / guidance excerpts:**")
        for chunk in rag_chunks:
            snippet = chunk["text"].strip().replace("\n", "\n  ")
            flag = "  ⚠ flagged content excluded from consideration" if chunk.get("injection_flagged") else ""
            lines.append(f"- {snippet}\n\n  *Source: [Doc: {chunk['citation']}]{flag}*")
    else:
        lines.append(
            "\nNo document passages met the retrieval confidence threshold for this question — "
            "treat the API-derived findings above as provisional until a relevant procedure is "
            "located, and consider a broader document search."
        )

    if not lines:
        return (
            "I could not resolve an asset, alarm, or applicable procedure for this question. Try "
            'naming a specific asset (e.g. "Boiler Feed Pump 101") or alarm.'
        )

    return "\n".join(lines)
