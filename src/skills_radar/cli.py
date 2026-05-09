"""CLI - `skills-radar serve | index | list | doctor | version`."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from skills_radar import __version__
from skills_radar.config import Config

app = typer.Typer(
    name="skills-radar",
    help="Lazy-loading skill discovery for Claude Code via MCP.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=False)
err_console = Console(stderr=True)


@app.callback()
def _root(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose logging")] = False,
) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@app.command()
def serve(
    transport: Annotated[
        str, typer.Option("--transport", "-t", help="Transport: stdio | http")
    ] = "stdio",
    host: Annotated[
        str | None, typer.Option("--host", "-H", help="HTTP bind host (default 127.0.0.1)")
    ] = None,
    port: Annotated[
        int | None, typer.Option("--port", "-p", help="HTTP port (default 6580)")
    ] = None,
    path: Annotated[
        str | None, typer.Option("--path", help="HTTP route path (default /mcp)")
    ] = None,
    stateless: Annotated[
        bool | None,
        typer.Option(
            "--stateless/--stateful",
            help="Stateless HTTP for horizontal scaling (default true)",
        ),
    ] = None,
    json_response: Annotated[
        bool | None,
        typer.Option(
            "--json/--sse-stream",
            help="JSON responses (default) or SSE streaming",
        ),
    ] = None,
    watch: Annotated[
        bool | None,
        typer.Option(
            "--watch/--no-watch",
            help="Hot-reload on SKILL.md changes (overrides config.watcher.enabled)",
        ),
    ] = None,
) -> None:
    """Start the MCP server (stdio for local Claude Code, http for production)."""
    if transport == "stdio":
        from skills_radar.mcp_server import run_stdio

        run_stdio(watch=watch)
    elif transport == "http":
        from skills_radar.mcp_server import run_http

        run_http(
            host=host,
            port=port,
            path=path,
            stateless=stateless,
            json_response=json_response,
            watch=watch,
        )
    else:
        err_console.print(f"[red]Unknown transport: {transport!r}[/red]")
        raise typer.Exit(2)


@app.command()
def index(
    rebuild: Annotated[bool, typer.Option("--rebuild", help="Drop existing index first")] = False,
) -> None:
    """Scan configured paths and (re)index all SKILL.md files."""
    from skills_radar.app import AppContext

    ctx = AppContext()
    n = ctx.reindex(rebuild=rebuild)
    console.print(f"[green]✓[/green] Indexed [bold]{n}[/bold] skills")


@app.command(name="list")
def list_skills(
    tag: Annotated[str | None, typer.Option("--tag", help="Filter by hub-tag")] = None,
    trust: Annotated[
        str | None,
        typer.Option("--trust", help="Filter by trust tier (trusted|verified|user|untrusted)"),
    ] = None,
) -> None:
    """List indexed skills with metadata."""
    from skills_radar.app import AppContext

    ctx = AppContext()
    items = ctx.store.list_all()
    table = Table(title=f"Indexed skills ({len(items)})")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Trust", style="yellow")
    table.add_column("Scope", style="dim")
    table.add_column("Description", overflow="fold")

    rows = 0
    for item in items:
        meta = item["metadata"]
        if tag:
            tags_csv = meta.get("hub_tags", "")
            tags_list = [t.strip().lower() for t in tags_csv.split(",") if t.strip()]
            if tag.lower() not in tags_list:
                continue
        if trust and meta.get("trust", "") != trust:
            continue
        table.add_row(
            item["id"],
            meta.get("trust", "?"),
            meta.get("scope", "?")[:40],
            (meta.get("description", "") or "-")[:80],
        )
        rows += 1

    if rows == 0:
        console.print("[yellow]No skills match the filters.[/yellow]")
    else:
        console.print(table)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Free-text search query")],
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="Number of matches")] = 5,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Filter by hub-tag (repeatable)")
    ] = None,
) -> None:
    """Run a hybrid search against the index (mirrors `search_skills` MCP tool)."""
    from skills_radar.app import AppContext

    ctx = AppContext()
    matches = ctx.hybrid_search(query=query, top_k=top_k, tags=tag)
    if not matches:
        console.print("[yellow]No matches.[/yellow]")
        return

    table = Table(title=f"Top {len(matches)} matches for: {query!r}")
    table.add_column("Score", style="green", justify="right")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Trust", style="yellow")
    table.add_column("Description", overflow="fold")
    for m in matches:
        table.add_row(
            f"{m['score']:.3f}",
            m["name"],
            m["metadata"].get("trust", "?"),
            (m["metadata"].get("description", "") or "-")[:80],
        )
    console.print(table)


@app.command(name="mini-index")
def mini_index_cmd(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output path (default: ~/.claude/SKILLS-INDEX.md)"),
    ] = None,
    group_by: Annotated[
        str,
        typer.Option("--group-by", help="Group by 'hub_tags' (default) or 'scope'"),
    ] = "hub_tags",
) -> None:
    """Generate the mini-index markdown file (Tier 1 of Two-Tier Discovery).

    Drop the resulting file's contents into your global CLAUDE.md so Claude
    Code knows what's available without paying the full skill-listing budget.
    """
    from skills_radar.app import AppContext
    from skills_radar.mini_index import generate_mini_index

    ctx = AppContext()
    items = ctx.store.list_all()
    if not items:
        err_console.print("[yellow]No skills indexed - run `skills-radar index` first.[/yellow]")
        raise typer.Exit(1)
    out = generate_mini_index(items, output=output, group_by=group_by)
    console.print(f"[green]✓[/green] Wrote mini-index ({len(items)} skills) to {out}")


@app.command()
def tui(
    refresh: Annotated[
        float, typer.Option("--refresh", "-r", help="Refresh interval in seconds")
    ] = 2.0,
) -> None:
    """Live read-only dashboard - trust breakdown, recent events, top queries.

    Telemetry must be enabled (config.telemetry.enabled: true) for the
    recent-events stream to populate. Press Ctrl+C to quit.
    """
    from skills_radar.tui import run_tui

    run_tui(refresh_seconds=refresh)


@app.command()
def stats() -> None:
    """Show local usage telemetry summary (top searches, miss rate, top loaded)."""
    from datetime import datetime

    from skills_radar.telemetry import Telemetry

    config = Config.load()
    tel = Telemetry(enabled=True, db_path=config.telemetry.db_path)
    summary = tel.stats_summary()

    if not summary["exists"]:
        if not config.telemetry.enabled:
            console.print(
                "[yellow]Telemetry disabled.[/yellow] Enable in "
                f"{Config.default_path()} (set telemetry.enabled: true)."
            )
        else:
            console.print("[yellow]No events yet.[/yellow] Run a few searches first.")
        return

    console.print("[bold]skills-radar usage stats[/bold]")
    console.print(f"DB: {summary['db_path']}")
    if not config.telemetry.enabled:
        console.print(
            "[dim]Note: telemetry.enabled=false in config - no new events being recorded.[/dim]"
        )
    console.print()

    totals = summary["totals"]
    table = Table(title="Event totals")
    table.add_column("Kind", style="cyan")
    table.add_column("Count", style="green", justify="right")
    for kind, count in sorted(totals.items()):
        table.add_row(kind, str(count))
    console.print(table)
    console.print()

    if summary["top_loaded"]:
        table = Table(title=f"Top loaded skills ({summary['totals'].get('load', 0)} loads)")
        table.add_column("Skill", style="cyan")
        table.add_column("Loads", style="green", justify="right")
        for name, count in summary["top_loaded"]:
            table.add_row(name, str(count))
        console.print(table)
        console.print()

    if summary["top_queries"]:
        miss_pct = summary["miss_rate"] * 100.0
        miss_color = "red" if miss_pct > 30 else "yellow" if miss_pct > 15 else "green"
        table = Table(
            title=f"Top queries (miss rate: [{miss_color}]{miss_pct:.1f}%[/{miss_color}] "
            f"of {summary['total_searches']} searches)"
        )
        table.add_column("Query", style="cyan", overflow="fold")
        table.add_column("Count", style="green", justify="right")
        for query, count in summary["top_queries"]:
            table.add_row(query[:60], str(count))
        console.print(table)
        console.print()

    recent = tel.fetch_recent(limit=10)
    if recent:
        table = Table(title="Recent events (last 10)")
        table.add_column("When", style="dim")
        table.add_column("Kind", style="yellow")
        table.add_column("Detail", overflow="fold")
        for ev in recent:
            ts = datetime.fromtimestamp(ev["ts"]).strftime("%H:%M:%S")
            d = ev["payload"]
            if ev["kind"] == "search":
                detail = (
                    f"{d.get('query', '')[:40]} → top1={d.get('top1_score', 0):.2f} "
                    f"({d.get('latency_ms', 0):.0f}ms)"
                )
            elif ev["kind"] == "load":
                detail = (
                    f"{d.get('skill_name', '')} ({d.get('trust', '?')}, "
                    f"{d.get('body_len', 0)}B, {d.get('latency_ms', 0):.0f}ms)"
                )
            elif ev["kind"] == "index":
                detail = (
                    f"count={d.get('count', 0)} duration={d.get('duration_ms', 0):.0f}ms "
                    f"rebuild={d.get('rebuild', False)}"
                )
            else:
                detail = str(d)[:80]
            table.add_row(ts, ev["kind"], detail)
        console.print(table)


@app.command()
def doctor() -> None:
    """Sanity check: paths, embedder, store, transport."""
    config = Config.load()
    console.print(f"[bold]skills-radar v{__version__}[/bold]")
    console.print(f"Config:  {Config.default_path()}")
    console.print()

    console.print("[bold]Paths:[/bold]")
    for p in config.paths:
        ep = p.expanduser()
        ok = "✓" if ep.exists() else "✗"
        skill_count = sum(1 for _ in ep.rglob("SKILL.md")) if ep.exists() else 0
        console.print(f"  {ok} {ep}  [dim]({skill_count} SKILL.md found)[/dim]")
    console.print()

    console.print("[bold]Embedder:[/bold]")
    console.print(f"  backend: {config.embedder.backend}")
    console.print(f"  model:   {config.embedder.model}")
    console.print()

    console.print("[bold]Store:[/bold]")
    console.print(f"  backend: {config.store.backend}")
    console.print(f"  path:    {config.store.path}")
    try:
        from skills_radar.store import SkillStore

        store = SkillStore(config.store.path)
        console.print(f"  indexed: {store.count()} skills")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]Store error: {exc}[/red]")
    console.print()

    console.print("[bold]Transport:[/bold]")
    console.print(f"  default: {config.transport.mode}")
    if config.transport.mode == "http":
        console.print(f"  port:    {config.transport.http_port}")


@app.command()
def version() -> None:
    """Print version and exit."""
    console.print(__version__)


@app.command(name="config-init")
def config_init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing config")] = False,
) -> None:
    """Write a default config.yaml at the XDG location."""
    target = Config.default_path()
    if target.exists() and not force:
        err_console.print(f"[yellow]{target} already exists. Use --force to overwrite.[/yellow]")
        raise typer.Exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    sample = (Path(__file__).parent.parent.parent / "examples" / "config.yaml.example").read_text(
        encoding="utf-8"
    )
    target.write_text(sample, encoding="utf-8")
    console.print(f"[green]✓[/green] Wrote default config to {target}")


if __name__ == "__main__":
    app()
