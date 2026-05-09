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

from skill_radar import __version__
from skill_radar.app import AppContext

logger = logging.getLogger("skill-radar.mcp")

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
    "skill-radar",
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
) -> dict[str, Any]:
    """Search Claude Code skills by intent (hybrid BM25 + semantic).

    Returns top-k matches with name, description, trust, score. Use when
    intent is clear but the right skill name isn't.
    """
    app = _get_app()
    matches = app.hybrid_search(query=query, top_k=top_k, tags=tags)
    return {
        "matches": [
            {
                "name": m["name"],
                "description": m["metadata"].get("description", ""),
                "when_to_use": m["metadata"].get("when_to_use", ""),
                "trust": m["metadata"].get("trust", "untrusted"),
                "score": round(m["score"], 4),
                "scope": m["metadata"].get("scope", "unknown"),
                "hub_tags": _csv_to_list(m["metadata"].get("hub_tags", "")),
            }
            for m in matches
        ],
        "query_processed": query,
        "total_indexed": app.store.count(),
        "weights": {
            "semantic": app.config.retrieval.hybrid_weight_semantic,
            "lexical": app.config.retrieval.hybrid_weight_lexical,
        },
    }


@mcp.tool()
async def load_skill(name: str) -> dict[str, Any]:
    """Load full SKILL.md content by name. Returns sanitized body + trust tier.

    Use when you know the skill name. Body re-read from disk on every call
    so live edits are picked up.
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

    return {
        "name": record.name,
        "frontmatter": _strip_cli_only_fields(record.frontmatter),
        "description": record.description,
        "when_to_use": record.when_to_use,
        "body_markdown": record.body_sanitized,
        "trust": record.trust.value,
        "scope": record.scope,
        "hub_tags": record.hub_tags,
        "bundled_files": record.bundled_files,
        "warnings": record.warnings,
        "version": __version__,
    }


def _csv_to_list(s: str) -> list[str]:
    if not s:
        return []
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
    from skill_radar.watcher import WatcherService

    watcher = WatcherService(app)
    watcher.start()
    logger.info("Hot-reload enabled (watching %d roots)", len(app.config.paths))


def run_stdio(*, watch: bool = False) -> None:
    """Entry point for stdio transport.

    Use for: local Claude Code dev, single-client subprocess. Stdout is
    reserved for JSON-RPC; all logs go to stderr.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting skill-radar v%s on stdio transport", __version__)

    if watch:
        _maybe_start_watcher()

    mcp.run(transport="stdio")


def run_http(
    *,
    host: str | None = None,
    port: int | None = None,
    path: str | None = None,
    stateless: bool | None = None,
    json_response: bool | None = None,
    watch: bool = False,
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
    cfg = _get_app().config.transport
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
        "skill-radar",
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
        "Starting skill-radar v%s on streamable-http at http://%s:%d%s",
        __version__,
        use_host,
        use_port,
        use_path,
    )
    logger.info("Mode: stateless=%s, json_response=%s", use_stateless, use_json)

    if watch:
        _maybe_start_watcher()

    mcp.run(transport="streamable-http")
