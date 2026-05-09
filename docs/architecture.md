# Architecture - Two-Tier Discovery

> Deep dive into how skills-radar works under the hood. For the user-facing TL;DR see [README](../README.md). For the full PRD see [SPEC.md](../SPEC.md).

## The discovery dilemma

Naive RAG over skills fails because of a chicken-and-egg problem:

> If the agent doesn't see the skills exist, it never queries the index. If it never queries the index, the lazy loading is pointless.

This is why most "MCP skill server" projects in the wild stay unused - the agent has no signal that the server is relevant to the current task.

## Solution - Two-Tier Discovery

We split the discovery into two complementary signals:

### Tier 1 - Mini-index (always preloaded, ~1k tokens)

A flat list of `name + 1-line summary` for every indexed skill, written to `~/.claude/SKILLS-INDEX.md` and imported in the user's global `CLAUDE.md`. Example:

```markdown
# Skills available (search via skills-radar MCP)

## Accessibility
- a11y-orchestrator - full WCAG audit, dispatches 7 agents
- a11y-fix - auto-fix common WCAG violations in Vue 3/Nuxt
- wcag-toolkit-lead - sdet-wcag-toolkit (audit/fix/report router)

## Performance
- perf-orchestrator - full perf audit, dispatches 5 agents
- perf-vue-runtime - Vue 3 runtime perf (re-renders, watchers, INP)
- perf-bundle-analyzer - JS/CSS bundle size, tree-shaking
...
```

Why this matters:
- Agent sees skills exist → triggers querying skills-radar
- ~80 skills × ~12 chars/name + ~50 chars/summary ≈ ~5k chars ≈ 1k tokens
- Categories help agent pre-filter mentally before querying

### Tier 2 - On-demand load (via MCP)

When the agent decides a skill is needed, it calls one of two MCP tools:

#### `search_skills(query, top_k=5, tags=None)`

Used when intent is fuzzy. Returns top-k matches by hybrid retrieval (BM25 + dense embeddings).

#### `load_skill(name)`

Used when name is obvious from intent (e.g., user explicitly named the skill). Returns full sanitized SKILL.md.

## Hybrid retrieval

Pure dense embeddings under-perform on short technical descriptions. Pure BM25 misses semantic matches. We combine:

```
final_score = w_semantic * cosine_sim + w_lexical * bm25_score
```

Defaults: `w_semantic = 0.7, w_lexical = 0.3`. Tunable per-deployment.

Why these weights: descriptions are short (50-300 chars), keyword overlap matters, but semantic similarity catches synonyms (e.g., query "memory leak" matching skill "perf-vue-runtime" which talks about "watcher leaks").

## Indexing pipeline

```
SKILL.md file
   │
   ▼
[parse YAML frontmatter] ─── reject if invalid (reserved name, missing fields)
   │
   ▼
[extract description + when_to_use] ─── this is the indexed text
   │
   ▼
[sanitize] ─── strip injection patterns, validate paths
   │
   ▼
[assign trust tier] ─── based on source path
   │
   ▼
[embed] ─── sentence-transformers/all-MiniLM-L6-v2 by default
   │
   ▼
[store in ChromaDB] ─── (vector, metadata, text) tuple
   │
   ▼
[update BM25 corpus] ─── tokenized text added to in-memory index
   │
   ▼
[notify agent] ─── if HTTP transport, send tools/list_changed notification
```

Body of SKILL.md is **never** indexed for retrieval - only loaded on `load_skill`. This keeps the index small, focused, and accurate.

## Hot reload (file watcher)

`watchdog` watches all configured paths. Events:

- **Created / Modified** → re-index that single file (full pipeline above)
- **Deleted** → remove from store + BM25 corpus
- **Moved** → delete old, index new

Re-indexing is incremental - single SKILL.md update is <100ms.

For Streamable HTTP transport, server sends `notifications/tools/list_changed` to all connected clients (per MCP spec). Stdio clients don't get notifications - they query on each call (acceptable for local dev).

## Trust tier assignment

Trust tier is determined at ingest time, based on source path:

```python
def determine_trust(skill_path: Path, config: Config) -> TrustTier:
    if skill_path in config.trust.trusted_paths:
        return TrustTier.TRUSTED
    if any(skill_path.is_relative_to(p) for p in [
        Path.home() / ".claude" / "plugins" / "cache" / "claude-plugins-official",
    ]):
        return TrustTier.VERIFIED
    if any(skill_path.is_relative_to(p) for p in [
        Path.home() / ".claude" / "skills",
        # project skills
    ]):
        return TrustTier.USER
    return TrustTier.UNTRUSTED
```

Trust tier is exposed in `load_skill` response. Agents (and downstream policies) can refuse to execute UNTRUSTED skills.

## Sanitization

On every ingest (regardless of trust):

1. **Frontmatter validation** - `name` ≤64 chars, no reserved words, lowercase + hyphens
2. **Size limit** - default 64KB per SKILL.md (configurable)
3. **XML strip** - remove `<system>`, `<override>`, `<jailbreak>`, etc. tags
4. **Path normalization** - reject backslashes, `..` traversal in `paths:` field
5. **Live-execution detection** - flag (or strip, per config) `` !`...` `` syntax for non-Claude-Code clients
6. **Pattern blocklist** - regex catalog of known injection patterns (configurable, file-based)

Patterns blocked by default (`blocked_patterns.txt`):
```
ignore (?:all )?previous instructions
disregard your system prompt
you are (?:now|actually) a [a-z]+
```

## Transport - why Streamable HTTP

Per MCP Python SDK guidance (May 2026):

| Transport | Use case |
|---|---|
| **stdio** | Local dev, single-client, simple |
| **streamable-http** | Production, horizontal scaling, multi-client, `stateless_http=True` |
| **sse** | Legacy - do not use for new servers |

We default to stdio for first-run simplicity (just works with Claude Code's `.mcp.json`). HTTP is opt-in via `--transport http` for production / shared / Docker deployments.

## Out-of-scope (consciously)

- **Skill execution** - we don't run skills. We only discover and serve them. Execution is the agent's job.
- **Skill authoring** - there's no `skills-radar create` command. Use [skill-creator](https://github.com/anthropics/claude-code/tree/main/skills/skill-creator) or write SKILL.md by hand.
- **Multi-tenant auth** - local-first tool. If you need RBAC, run separate instances per user.
- **Versioning of skills** - handled by Claude Code's native plugin/marketplace system. We index whatever's on disk.

## Tradeoffs taken

| Decision | Why |
|---|---|
| ChromaDB > FAISS+SQLite | Built-in metadata, embedded persistence, matches `mcp-skillset` prior art. FAISS available as pluggable backend for users who care. |
| sentence-transformers > MLX (default) | Cross-platform. MLX is faster on Mac but excludes Linux/Windows users. MLX is opt-in. |
| 2 tools (search, load), not more | Mirror Anthropic's Tool Search; admin tools live in CLI, not MCP. Eat your own dogfood - every tool description is a token cost in agent context. |
| Body NOT indexed | Body bloat destroys similarity scoring. `description + when_to_use` is the discovery primitive. |
| Trust tier from path | Simple, deterministic, transparent. Crypto signing punted to v0.2. |

## Open questions (see SPEC §15)

1. Trust registry for VERIFIED tier
2. `hub-tags` taxonomy publishing
3. Telemetry / usage stats from v0.1 or post-1.0
