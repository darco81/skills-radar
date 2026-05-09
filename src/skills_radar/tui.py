"""TUI dashboard - rich.Live based real-time view.

Read-only. Refreshes every `refresh_seconds` (default 2.0). Reads from
the telemetry DB (must be enabled in config) plus a one-shot AppContext
init for skill counts and trust breakdown. No keyboard handling - Ctrl+C
to quit.

Designed for: demo material, "see your skills-radar working" while a
Claude Code session is running and querying the MCP. Telemetry must be
enabled (config.telemetry.enabled = true) for the live event stream
to populate.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime
from typing import Any

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from skills_radar import __version__
from skills_radar.config import Config
from skills_radar.telemetry import Telemetry

REFRESH_DEFAULT = 2.0


def _trust_breakdown(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter((item.get("metadata") or {}).get("trust", "unknown") for item in items)


def _format_bar(value: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "░" * width
    filled = int(round((value / total) * width))
    return "█" * filled + "░" * (width - filled)


def _build_header(
    config: Config,
    skills_count: int,
    paths_ok: int,
    paths_total: int,
) -> Panel:
    txt = Text()
    txt.append("📡 skills-radar v", style="bold cyan")
    txt.append(__version__, style="bold cyan")
    txt.append("  ·  ", style="dim")
    txt.append(f"{skills_count} skills indexed", style="green")
    txt.append("  ·  ", style="dim")
    txt.append(f"{paths_ok}/{paths_total} paths reachable", style="yellow")
    txt.append("  ·  embedder=", style="dim")
    txt.append(config.embedder.backend, style="magenta")
    txt.append("  ·  store=", style="dim")
    txt.append(config.store.backend, style="magenta")
    txt.append("  ·  rewriter=", style="dim")
    txt.append(
        config.retrieval.rewriter.backend if config.retrieval.rewriter.enabled else "off",
        style="magenta" if config.retrieval.rewriter.enabled else "dim",
    )
    return Panel(txt, padding=(0, 1))


def _build_trust_panel(breakdown: Counter[str], total: int) -> Panel:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="yellow", no_wrap=True)
    table.add_column()
    table.add_column(style="green", justify="right")
    order = ["trusted", "verified", "user", "untrusted", "unknown"]
    for tier in order:
        n = breakdown.get(tier, 0)
        if n == 0 and tier == "unknown":
            continue
        bar = _format_bar(n, total)
        table.add_row(tier.upper(), bar, str(n))
    return Panel(table, title="Trust tier breakdown", title_align="left")


def _build_top_queries_panel(summary: dict[str, Any]) -> Panel:
    if not summary.get("top_queries"):
        return Panel(
            Text("(no queries yet - run a search)", style="dim"),
            title="Top queries",
            title_align="left",
        )
    miss_pct = summary.get("miss_rate", 0.0) * 100.0
    miss_color = "red" if miss_pct > 30 else "yellow" if miss_pct > 15 else "green"
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan")
    table.add_column(style="green", justify="right")
    for q, n in summary["top_queries"][:8]:
        table.add_row(q[:50], str(n))
    title = (
        f"Top queries  ·  miss [{miss_color}]{miss_pct:.0f}%[/{miss_color}]"
        f"  of {summary.get('total_searches', 0)}"
    )
    return Panel(table, title=title, title_align="left")


def _build_top_loaded_panel(summary: dict[str, Any]) -> Panel:
    if not summary.get("top_loaded"):
        return Panel(
            Text("(no skills loaded yet)", style="dim"),
            title="Top loaded skills",
            title_align="left",
        )
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan")
    table.add_column(style="green", justify="right")
    for name, n in summary["top_loaded"][:8]:
        table.add_row(name, str(n))
    return Panel(table, title="Top loaded skills", title_align="left")


def _build_recent_panel(events: list[dict[str, Any]]) -> Panel:
    if not events:
        return Panel(
            Text("(no events yet)", style="dim"),
            title="Recent events",
            title_align="left",
        )
    table = Table.grid(padding=(0, 1))
    table.add_column(style="dim", no_wrap=True)
    table.add_column(style="yellow", no_wrap=True)
    table.add_column(overflow="ellipsis", no_wrap=True)
    for ev in events[:14]:
        ts = datetime.fromtimestamp(ev["ts"]).strftime("%H:%M:%S")
        d = ev["payload"]
        if ev["kind"] == "search":
            top1 = float(d.get("top1_score", 0.0))
            color = "green" if top1 >= 0.6 else "yellow" if top1 >= 0.4 else "red"
            detail = (
                f"[{color}]{top1:.2f}[/{color}]  "
                f"{d.get('query', '')[:42]}  ({d.get('latency_ms', 0):.0f}ms)"
            )
        elif ev["kind"] == "load":
            color = "green" if d.get("found") else "red"
            detail = (
                f"[{color}]{d.get('skill_name', '?')}[/{color}]  "
                f"trust={d.get('trust', '?')}  "
                f"({d.get('body_len', 0)}B, {d.get('latency_ms', 0):.0f}ms)"
            )
        elif ev["kind"] == "index":
            detail = (
                f"count={d.get('count', 0)}  "
                f"{d.get('duration_ms', 0):.0f}ms  "
                f"rebuild={d.get('rebuild', False)}"
            )
        else:
            detail = str(d)[:60]
        table.add_row(ts, ev["kind"][:6], detail)
    return Panel(table, title="Recent events  ·  live", title_align="left")


def _build_footer(refresh_seconds: float) -> Panel:
    txt = Text()
    txt.append("Refreshing every ", style="dim")
    txt.append(f"{refresh_seconds:.1f}s", style="cyan")
    txt.append("  ·  Ctrl+C to quit", style="dim")
    return Panel(txt, padding=(0, 1))


def _render(
    config: Config,
    tel: Telemetry,
    skills_count: int,
    trust_breakdown: Counter[str],
    paths_ok: int,
    paths_total: int,
    refresh_seconds: float,
) -> Layout:
    summary = tel.stats_summary()
    recent = tel.fetch_recent(limit=14)

    layout = Layout()
    layout.split(
        Layout(_build_header(config, skills_count, paths_ok, paths_total), size=3, name="header"),
        Layout(name="body"),
        Layout(_build_footer(refresh_seconds), size=3, name="footer"),
    )
    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )
    layout["body"]["left"].split(
        Layout(_build_trust_panel(trust_breakdown, skills_count), size=9),
        Layout(_build_top_queries_panel(summary)),
        Layout(_build_top_loaded_panel(summary)),
    )
    layout["body"]["right"].update(_build_recent_panel(recent))
    return layout


def run_tui(refresh_seconds: float = REFRESH_DEFAULT) -> None:
    """Main TUI entry. Boots AppContext once for skills info, then loops."""
    from skills_radar.app import AppContext

    console = Console()
    console.print("[bold]Booting skills-radar TUI...[/bold]  (this loads the embedder once)")

    ctx = AppContext()
    items = ctx.store.list_all()
    skills_count = len(items)
    trust_breakdown = _trust_breakdown(items)
    paths_total = len(ctx.config.paths)
    paths_ok = sum(1 for p in ctx.config.paths if p.expanduser().exists())

    tel = Telemetry(enabled=True, db_path=ctx.config.telemetry.db_path)

    if not ctx.config.telemetry.enabled:
        console.print(
            "[yellow]⚠  Telemetry is disabled in config - recent events stream will be empty.[/yellow]"
        )
        console.print(
            f"[dim]Enable in {Config.default_path()} (telemetry.enabled: true) for live events.[/dim]"
        )

    try:
        with Live(
            _render(
                ctx.config,
                tel,
                skills_count,
                trust_breakdown,
                paths_ok,
                paths_total,
                refresh_seconds,
            ),
            refresh_per_second=4,
            screen=True,
            console=console,
        ) as live:
            while True:
                time.sleep(refresh_seconds)
                # Rebuild snapshot - store count may change if user runs reindex elsewhere
                items = ctx.store.list_all()
                skills_count = len(items)
                trust_breakdown = _trust_breakdown(items)
                live.update(
                    _render(
                        ctx.config,
                        tel,
                        skills_count,
                        trust_breakdown,
                        paths_ok,
                        paths_total,
                        refresh_seconds,
                    )
                )
    except KeyboardInterrupt:
        console.print("\n[bold]TUI stopped.[/bold]")


# Self-render once for screenshot/test purposes (no live loop).
def render_snapshot() -> Group:
    from skills_radar.app import AppContext

    ctx = AppContext()
    items = ctx.store.list_all()
    tel = Telemetry(enabled=True, db_path=ctx.config.telemetry.db_path)
    paths_total = len(ctx.config.paths)
    paths_ok = sum(1 for p in ctx.config.paths if p.expanduser().exists())

    layout = _render(
        ctx.config,
        tel,
        len(items),
        _trust_breakdown(items),
        paths_ok,
        paths_total,
        REFRESH_DEFAULT,
    )
    return Group(layout)
