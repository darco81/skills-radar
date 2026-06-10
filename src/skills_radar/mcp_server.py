"""MCP server - FastMCP with two tools: search_skills, load_skill.

Mirrors Anthropic's Tool Search Tool pattern (search-then-load).
Stdio transport for local dev (default); HTTP added in F2.

CRITICAL: do NOT print() to stdout - stdio transport uses stdout for JSON-RPC.
All logs go to stderr.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from skills_radar import __version__
from skills_radar.app import AppContext

logger = logging.getLogger("skills-radar.mcp")

# Single global AppContext. Initialized lazily on first tool call to keep
# startup fast and let `--help` etc. not load the embedding model.
_app: AppContext | None = None


def _get_app() -> AppContext:
    global _app  # noqa: PLW0603
    if _app is None:
        logger.info("Initializing AppContext (first tool call)...")
        _app = AppContext()
        if _app.store.count() == 0:
            logger.info("Empty store - running initial reindex")
            _app.reindex()
    return _app


# Tool descriptions deliberately under ~200 chars - they live in agent context.
mcp = FastMCP(
    "skills-radar",
    instructions=(
        "Lazy-loading skill discovery. Two tools: search_skills(query) for fuzzy intent, "
        "load_skill(name) when name is known. Mirror Anthropic Tool Search pattern. "
        "Skill content has trust tiers - check 'trust' field before acting."
    ),
)


@mcp.tool()
async def search_skills(
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Search Claude Code skills, agents and commands by intent (hybrid BM25 + semantic).

    Returns top-k matches with name, kind, description, trust, score. Use when
    intent is clear but the right resource name isn't. Optional kind filter:
    'skill' | 'agent' | 'command'.
    """
    app = _get_app()
    matches = app.hybrid_search(query=query, top_k=top_k, tags=tags, kind=kind)
    return {
        "matches": [_match_to_entry(m) for m in matches],
        "query_processed": query,
        "total_indexed": app.store.count(),
        "weights": {
            "semantic": app.config.retrieval.hybrid_weight_semantic,
            "lexical": app.config.retrieval.hybrid_weight_lexical,
        },
    }


@mcp.tool()
async def load_skill(name: str, sandbox: bool = False) -> dict[str, Any]:
    """Load full resource content (skill / agent / command) by name.

    Returns sanitized body + trust tier. Body re-read from disk on every
    call so live edits are picked up. Agents and commands use namespaced
    names ('agent:qa-reporter', 'cmd:perf-report'); bare names resolve
    via skill → agent → command fallback.

    Args:
        name: resource name from search_skills or mini-index.
        sandbox: when True, also read bundled files (one level deep from
            SKILL.md), validate against safe-extension whitelist + size
            caps + path traversal + symlinks, and return their sanitized
            UTF-8 content under `sandboxed_files`. Default False (just
            list filenames in `bundled_files`).
    """
    app = _get_app()
    record, stored_meta = app.load_record(name)
    if record is None:
        return {
            "error": "skill_not_found",
            "name": name,
            "message": (
                f"Skill {name!r} not in index. Try search_skills() to discover available skills."
            ),
            "stored_meta_present": stored_meta is not None,
        }

    sandboxed_files: dict[str, str] = {}
    sandbox_warnings: list[str] = []
    if sandbox and record.bundled_files:
        from pathlib import Path

        from skills_radar.sandbox import sandbox_bundled_files

        sandboxed_files, sandbox_warnings = sandbox_bundled_files(
            Path(record.path),
            record.bundled_files,
            strip_live_exec=app.config.sanitization.strip_live_exec,
        )

    return {
        "name": record.name,
        "uid": record.uid,
        "kind": record.kind,
        "frontmatter": _strip_cli_only_fields(record.frontmatter),
        "description": record.description,
        "when_to_use": record.when_to_use,
        "body_markdown": record.body_sanitized,
        "trust": record.trust.value,
        "scope": record.scope,
        "hub_tags": record.hub_tags,
        "bundled_files": record.bundled_files,
        "sandboxed_files": sandboxed_files,
        "warnings": record.warnings + sandbox_warnings,
        "version": __version__,
    }


def _match_to_entry(m: dict[str, Any]) -> dict[str, Any]:
    """Shape one hybrid_search hit into a search_skills response entry.

    requires_tools / fallback_for_tools are exposed (not filtered) - the
    server can't know the client's toolset, so environment policy is the
    consuming agent's call. Same contract as the `trust` field.
    """
    meta = m["metadata"]
    return {
        "name": m["name"],
        "kind": meta.get("kind", "skill"),
        "description": meta.get("description", ""),
        "when_to_use": meta.get("when_to_use", ""),
        "trust": meta.get("trust", "untrusted"),
        "score": round(m["score"], 4),
        "scope": meta.get("scope", "unknown"),
        "hub_tags": _csv_to_list(meta.get("hub_tags", "")),
        "requires_tools": _csv_to_list(meta.get("requires_tools", "")),
        "fallback_for_tools": _csv_to_list(meta.get("fallback_for_tools", "")),
    }


def _csv_to_list(s: str | list[str]) -> list[str]:
    """ChromaDB coerces list metadata to CSV strings; Qdrant keeps lists as-is."""
    if not s:
        return []
    if isinstance(s, list):
        return [str(x).strip() for x in s if str(x).strip()]
    return [x.strip() for x in s.split(",") if x.strip()]


_CLI_ONLY_FIELDS = frozenset({"allowed-tools"})


def _strip_cli_only_fields(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Strip Claude-Code-CLI-only fields. SDK clients silently fail on these.

    Per research, `allowed-tools` is in CLI but not in API SDK. A hub serving
    multiple clients must strip it.
    """
    return {k: v for k, v in frontmatter.items() if k not in _CLI_ONLY_FIELDS}


def _maybe_start_watcher() -> None:
    app = _get_app()
    from skills_radar.watcher import WatcherService

    watcher = WatcherService(app)
    watcher.start()
    logger.info("Hot-reload enabled (watching %d roots)", len(app.config.paths))


def _resolve_watch(cli_flag: bool | None, app: AppContext | None = None) -> bool:
    """CLI --watch/--no-watch wins; otherwise read config.watcher.enabled."""
    if cli_flag is not None:
        return cli_flag
    if app is None:
        app = _get_app()
    return bool(app.config.watcher.enabled)


def run_stdio(*, watch: bool | None = None) -> None:
    """Entry point for stdio transport.

    Use for: local Claude Code dev, single-client subprocess. Stdout is
    reserved for JSON-RPC; all logs go to stderr.

    `watch=None`: read from config.watcher.enabled.
    `watch=True/False`: explicit CLI override.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting skills-radar v%s on stdio transport", __version__)

    if _resolve_watch(watch):
        _maybe_start_watcher()

    mcp.run(transport="stdio")


def run_http(
    *,
    host: str | None = None,
    port: int | None = None,
    path: str | None = None,
    stateless: bool | None = None,
    json_response: bool | None = None,
    watch: bool | None = None,
) -> None:
    """Entry point for Streamable HTTP transport.

    Use for: production, Docker, horizontal scaling, multi-client. Pair
    `stateless_http=True` + `json_response=True` for a horizontally
    scalable deployment behind a load balancer (per MCP SDK guidance).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = _get_app()
    cfg = app.config.transport
    use_host = host or cfg.http_host
    use_port = port or cfg.http_port
    use_path = path or cfg.http_path
    use_stateless = cfg.stateless_http if stateless is None else stateless
    use_json = cfg.json_response if json_response is None else json_response

    # FastMCP takes ALL transport params in the constructor - re-create the
    # global with HTTP-tuned flags and re-register both tools.
    global mcp  # noqa: PLW0603
    from mcp.server.fastmcp import FastMCP as _FastMCP

    new_mcp = _FastMCP(
        "skills-radar",
        instructions=getattr(mcp, "instructions", None),
        host=use_host,
        port=use_port,
        streamable_http_path=use_path,
        stateless_http=use_stateless,
        json_response=use_json,
    )
    new_mcp.tool()(search_skills)
    new_mcp.tool()(load_skill)
    mcp = new_mcp

    logger.info(
        "Starting skills-radar v%s on streamable-http at http://%s:%d%s",
        __version__,
        use_host,
        use_port,
        use_path,
    )
    logger.info("Mode: stateless=%s, json_response=%s", use_stateless, use_json)

    if _resolve_watch(watch, app):
        _maybe_start_watcher()

    mcp.run(transport="streamable-http")
