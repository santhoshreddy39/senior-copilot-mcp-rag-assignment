#!/usr/bin/env python3
"""Generates docs/architecture-diagram.png from a simple box/arrow layout —
kept as a script (rather than a static image only) so the diagram can be
regenerated if the architecture changes."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "architecture-diagram.png"

COLORS = {
    "gui": "#DCE9FA",
    "orch": "#FCE9CE",
    "mcp": "#DDF3E4",
    "api": "#F8D7DA",
    "rag": "#EADCF8",
    "border": "#33415C",
}


def box(ax, xy, w, h, text, color, fontsize=10, weight="bold"):
    x, y = xy
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.06",
        linewidth=1.6,
        edgecolor=COLORS["border"],
        facecolor=color,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        weight=weight,
        color="#1A1A2E",
        wrap=True,
    )
    return (x, y, w, h)


def arrow(ax, start, end, label="", style="-|>", color=COLORS["border"], lw=1.6, ls="solid"):
    a = FancyArrowPatch(
        start, end, arrowstyle=style, mutation_scale=14, linewidth=lw, color=color, linestyle=ls, shrinkA=2, shrinkB=2
    )
    ax.add_patch(a)
    if label:
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(mx, my + 0.15, label, ha="center", va="bottom", fontsize=8.5, color="#333")


def main() -> None:
    fig, ax = plt.subplots(figsize=(12, 9))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 13)
    ax.axis("off")
    ax.set_title(
        "Alarm Investigation and Procedure Guidance Copilot — Architecture", fontsize=14, weight="bold", pad=14
    )

    gui = box(ax, (4.3, 11.3), 3.4, 1.0, "Streamlit GUI\n(chat, trace, citations)", COLORS["gui"])

    orch_outer = box(ax, (1.0, 7.3), 10.0, 3.3, "", "#FFFFFF", fontsize=1)
    ax.text(
        1.3,
        10.35,
        "Copilot backend — orchestration layer  (apps/backend/)",
        fontsize=10.5,
        weight="bold",
        color="#5B4636",
    )

    nlu = box(ax, (1.5, 8.6), 2.4, 1.1, "NLU\n(intent + entities)", COLORS["orch"], fontsize=9)
    orch = box(ax, (4.3, 8.5), 2.9, 1.3, "Orchestrator\n(multi-step MCP\n+ RAG planning)", COLORS["orch"], fontsize=9)
    llm = box(ax, (7.7, 8.6), 2.8, 1.1, "LLM provider\n(OpenAI/Anthropic/\nAzure/Template)", COLORS["orch"], fontsize=9)

    mcp_client = box(ax, (2.2, 7.5), 3.2, 0.9, "MCP client (stdio)", COLORS["mcp"], fontsize=9)
    retriever = box(ax, (6.8, 7.5), 3.2, 0.9, "RAG retriever\n(TF-IDF + BM25 hybrid)", COLORS["rag"], fontsize=9)

    mcp_server = box(
        ax, (0.6, 5.2), 4.2, 1.1, "Alarm-Management MCP server\n(mcp-servers/alarm-management)", COLORS["mcp"]
    )
    documents = box(
        ax,
        (7.2, 5.2),
        4.2,
        1.1,
        "rag/documents/*.md\noperating procs, manuals,\ntroubleshooting, safety",
        COLORS["rag"],
        fontsize=9,
    )

    connector = box(
        ax, (0.6, 3.3), 4.2, 0.9, "Alarm API connector\n(auth, retries, trace propagation)", COLORS["mcp"], fontsize=9
    )

    alarm_api = box(ax, (0.6, 1.2), 4.2, 1.1, "Alarm Management API simulator\n(FastAPI; Bearer auth)", COLORS["api"])

    # arrows
    arrow(ax, (gui[0] + gui[2] / 2, gui[1]), (gui[0] + gui[2] / 2, 10.6), "HTTP /chat /mcp/tools /health")
    arrow(ax, (2.7, 8.6), (2.7, 8.4), "")
    arrow(ax, (4.3, 9.1), (3.9, 9.15), "")
    arrow(ax, (7.15, 9.1), (7.7, 9.15), "")
    arrow(ax, (3.8, 8.5), (3.8, 8.4), "asset/intent")
    arrow(ax, (5.8, 8.5), (5.3, 8.4), "tool calls")
    arrow(ax, (5.8, 8.5), (8.3, 8.4), "retrieval query")

    arrow(ax, (3.8, 7.5), (2.7, 6.3), "MCP protocol\n(subprocess, stdio)")
    arrow(ax, (8.4, 7.5), (9.3, 6.3), "reads")

    arrow(ax, (2.7, 5.2), (2.7, 4.2), "")
    arrow(ax, (2.7, 3.3), (2.7, 2.3), "HTTP + Bearer\n+ trace headers")

    plt.tight_layout()
    fig.savefig(OUT_PATH, dpi=160)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
