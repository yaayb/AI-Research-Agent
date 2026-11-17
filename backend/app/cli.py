"""Interactive terminal runner: ``python -m app.cli "topic" --depth deep --output ./reports``.

Design decision: the CLI consumes the very same telemetry event stream as the SSE API, rendering it
with ``rich`` (live status spinner, tool-call panels, comparison tables, saved-file paths).
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import uuid
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.agent.graph import answer_followup, build_graph, get_thread_values, stream_research
from app.agent.llm import ConfigError
from app.config import get_settings
from app.database import db
from app.memory.checkpointer import open_checkpointer

console = Console()
NODE_ICONS = {"recall_memory": "🧠", "plan_research": "🗺️", "approve_plan": "✅", "investigator_agent": "🔎",
              "execute_tools": "🛠️", "compare_sources": "⚖️", "reflect_coverage": "🪞", "synthesize_report": "📝"}


def render_event(ev: dict, status) -> None:
    t = ev["type"]
    if t == "node_start":
        status.update(f"{NODE_ICONS.get(ev['node'], '•')} [bold cyan]{ev['node']}[/] (loop {ev.get('iteration', 0) + 1})")
    elif t == "session_started":
        console.print(Panel.fit(f"[bold]{ev['topic']}[/]\ndepth={ev['depth']} (max {ev['max_iterations']} loops) · "
                                f"LLM={ev['llm']} · search={ev['search']}", title="DeepBrief AI", border_style="cyan"))
    elif t == "memory_recalled":
        console.print(f"🧠 Recalled [bold]{len(ev['items'])}[/] prior memories")
        for it in ev["items"][:4]:
            console.print(f"   [dim]({it['score']}) {it['text'][:110]}[/]")
    elif t == "plan":
        p = ev["plan"]
        body = f"[bold]Goal:[/] {p['research_goal']}\n" + "\n".join(f"  ? {q}" for q in p["sub_questions"])
        console.print(Panel(body, title="Research plan", border_style="blue"))
    elif t == "tool_call":
        arg = ev["args"].get("query") or ev["args"].get("url") or ev["args"]
        console.print(Panel(f"[bold yellow]{ev['tool']}[/]([green]\"{arg}\"[/])", border_style="yellow", expand=False))
    elif t == "tool_result":
        mark = "[green]✔[/]" if ev["ok"] else "[red]✘[/]"
        console.print(f"   {mark} {ev['summary']}")
    elif t == "source":
        console.print(f"   [dim]source[/] {ev['domain']} — {ev['title'][:70]} [{ev['status']}]")
    elif t == "comparison":
        console.print(f"⚖️  {ev['corroborated']} corroborated · {ev['disputed']} disputed · {ev['sources']} sources")
    elif t == "reflection":
        color = "green" if ev["decision"] == "synthesize" else "yellow"
        console.print(f"🪞 coverage [bold {color}]{ev['coverage_score']:.0%}[/] after loop {ev['iteration']}/{ev['max_iterations']} → {ev['decision']}")
        for q in ev["gap_queries"]:
            console.print(f"   gap: {q}")
    elif t == "memory_stored":
        console.print(f"💾 Stored [bold]{ev['count']}[/] items in long-term memory")
    elif t == "error":
        console.print(f"[bold red]Error:[/] {ev['message']}")


def print_comparison(vals: dict) -> None:
    comp = vals.get("comparison", {})
    t = Table(title="Source comparison", show_lines=True)
    for c in ("Domain", "Credibility", "Relevance", "Key takeaway"):
        t.add_column(c)
    for q in comp.get("source_quality_table", []):
        t.add_row(q["domain"], q["credibility_tier"], f"{q['relevance_score']:.2f}", q["key_takeaway"][:90])
    console.print(t)
    for d in comp.get("disputed_or_conflicting_claims", []):
        console.print(Panel("\n".join(f"{p['domain']}: {p['stance_or_figure']} ({p.get('published_date') or 'n/a'})"
                                      for p in d["positions"]), title=f"⚠ Disputed: {d['claim']}", border_style="red"))
    for c in comp.get("corroborated_claims", []):
        console.print(f"[green]✔ corroborated[/] {c['claim']} ({len(c['source_urls'])} sources)")


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.offline:
        settings.offline_test_mode = True
    session_id = args.session_id or uuid.uuid4().hex[:12]
    try:
        async with open_checkpointer(settings) as saver:
            graph = build_graph(saver, settings=settings)
            resume = None
            while True:
                interrupted = False
                with console.status("starting...") as status:
                    async for ev in stream_research(graph, args.topic, session_id, args.depth, args.approve_plan, resume, settings):
                        render_event(ev, status)
                        if ev["type"] == "plan_approval_required":
                            interrupted = True
                        elif ev["type"] == "error":
                            return 1
                if not interrupted:
                    break
                answer = console.input("Approve plan? [Enter = yes, or type extra search query]: ").strip()
                resume = {"initial_queries": None} if not answer else {"initial_queries": [answer]}
            vals = await get_thread_values(graph, session_id)
            print_comparison(vals)
            out = Path(args.output).resolve()
            out.mkdir(parents=True, exist_ok=True)
            saved = []
            for fmt, src in vals["artifacts"].items():
                dst = out / f"{session_id}.{fmt}"
                shutil.copyfile(src, dst)
                saved.append(dst)
            console.print(Panel("\n".join(f"📄 {p}" for p in saved), title="Saved report files", border_style="green"))
            console.print(f"Session id: [bold]{session_id}[/] (reuse with --session-id for follow-ups)")
            if args.chat:
                console.print("[bold]Follow-up chat[/] (empty line to exit)")
                while (q := console.input("[cyan]you> [/]").strip()):
                    console.print(Panel(await answer_followup(graph, session_id, q), title="answer"))
            return 0
    except ConfigError as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        return 2


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="DeepBrief AI autonomous research agent")
    p.add_argument("topic", help="Research topic or question")
    p.add_argument("--depth", choices=["quick", "deep"], default="quick", help="quick = 2 loops, deep = 4 loops")
    p.add_argument("--output", default="./reports", help="Directory for exported .md/.html/.pdf files")
    p.add_argument("--approve-plan", action="store_true", help="Pause for human approval of the research plan")
    p.add_argument("--chat", action="store_true", help="Open follow-up Q&A after the report")
    p.add_argument("--session-id", help="Custom thread id")
    p.add_argument("--offline", action="store_true", help="Deterministic fixtures + scripted LLM (no network/keys)")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
