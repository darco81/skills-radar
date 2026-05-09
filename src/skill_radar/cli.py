"""CLI - `skill-radar serve | index | list | doctor | version`."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from skill_radar import __version__
from skill_radar.config import Config

app = typer.Typer(
    name="skill-radar",
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
    port: Annotated[int, typer.Option("--port", "-p", help="HTTP port")] = 6580,
) -> None:
    """Start the MCP server."""
    if transport == "stdio":
        from skill_radar.mcp_server import run_stdio

        run_stdio()
    elif transport == "http":
        err_console.print("[yellow]HTTP transport ships in F2 - use stdio for now.[/yellow]")
        raise typer.Exit(1)
    else:
        err_console.print(f"[red]Unknown transport: {transport!r}[/red]")
        raise typer.Exit(2)


@app.command()
def index(
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Drop existing index first")
    ] = False,
) -> None:
    """Scan configured paths and (re)index all SKILL.md files."""
    from skill_radar.app import AppContext

    ctx = AppContext()
    n = ctx.reindex(rebuild=rebuild)
    console.print(f"[green]✓[/green] Indexed [bold]{n}[/bold] skills")


@app.command(name="list")
def list_skills(
    tag: Annotated[Optional[str], typer.Option("--tag", help="Filter by hub-tag")] = None,
    trust: Annotated[
        Optional[str],
        typer.Option("--trust", help="Filter by trust tier (trusted|verified|user|untrusted)"),
    ] = None,
) -> None:
    """List indexed skills with metadata."""
    from skill_radar.app import AppContext

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
        Optional[list[str]], typer.Option("--tag", help="Filter by hub-tag (repeatable)")
    ] = None,
) -> None:
    """Run a hybrid search against the index (mirrors `search_skills` MCP tool)."""
    from skill_radar.app import AppContext

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


@app.command()
def doctor() -> None:
    """Sanity check: paths, embedder, store, transport."""
    config = Config.load()
    console.print(f"[bold]skill-radar v{__version__}[/bold]")
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
        from skill_radar.store import SkillStore

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
