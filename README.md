# 📡 skill-radar

> **Lazy-loading skill discovery for Claude Code (and other MCP clients).**
> Stop bleeding context tokens on skills you might never use.

`skill-radar` is a local **MCP server** that mirrors Anthropic's [MCP Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) pattern - but for **Skills**. Instead of preloading every skill's metadata into the system prompt at session start (default Claude Code behavior), `skill-radar` exposes two tools (`search_skills`, `load_skill`) so the agent fetches only what's relevant to the current task.

**Why this exists:** Anthropic shipped Tool Search for MCP tools in late 2025 (85% token reduction, +8.6% accuracy on Opus 4.5). They haven't shipped the equivalent for Skills yet. With 80+ skills across personal, project, and plugin scopes, your `/doctor` is probably bleeding 5-10k tokens before you type a word. This fixes that.

> **Status:** 🚧 v0.1 in active development. Spec: [`SPEC.md`](./SPEC.md). MVP target: ~3-4h after spec approval.

---

## TL;DR

```bash
pip install skill-radar
skill-radar init                  # scans ~/.claude/skills + project skills
skill-radar serve                 # starts MCP server on stdio
```

Add to your Claude Code `.mcp.json`:

```json
{
  "mcpServers": {
    "skill-radar": {
      "command": "skill-radar",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

Restart Claude Code. Drop your skill descriptions in `skillOverrides`:

```json
{ "skillOverrides": { "*": "name-only" } }
```

Now Claude only sees skill **names** in the prompt (~1k tokens for 80 skills), and queries `skill-radar` for full descriptions when needed.

---

## How it works - Two-Tier Discovery

```
┌────────────────────────────────────────────────────────┐
│ Claude Code session                                    │
│  System prompt: mini-index (~1k tokens, names only)    │
│  MCP tools: search_skills, load_skill                  │
└──────────┬─────────────────────────────────────────────┘
           │
           ▼  intent: clear?
   ┌───────────────────────┐
   │ obvious name?         │
   └────┬─────────────┬────┘
        │ yes         │ no/ambiguous
        ▼             ▼
 load_skill(name)  search_skills(query)
                       │
                       ▼
              top-k matches w/ score
                       │
                       ▼ agent picks best
                  load_skill(best.name)
        ┌──────────────────────────┐
        │ Full SKILL.md content    │
        │ + trust tier + warnings  │
        └──────────────────────────┘
```

**Tier 1** (always, ~1k tokens): mini-index of skill names + 1-line summaries.
**Tier 2** (on demand): full SKILL.md body, fetched only when agent commits to using it.

Result: from ~6k tokens loaded upfront to ~1k tokens + on-demand. **~83% savings**, and you can scale to 500 skills without your prompt suffering.

---

## Features

- 🔍 **Hybrid retrieval** - BM25 (lexical) + dense embeddings (semantic), 70/30 by default
- 🔥 **Hot reload** - drop a SKILL.md, indexed in <1s (no Claude restart)
- 🛡️ **Threat model day-one** - trust tiers, prompt-injection scanning, size limits
- 🪶 **Light by default** - sentence-transformers (90MB) + ChromaDB (zero-deps)
- 🔌 **Pluggable** - swap embedder (MLX, OpenAI, Voyage), swap store (Qdrant, FAISS)
- 🌐 **Multi-client** - Claude Code, Cursor, Claude Desktop, custom agents
- 📡 **Streamable HTTP** transport for production; stdio for local dev
- ✈️ **Air-gapped** - pre-baked Docker image, offline embedding cache

---

## Project status

| Phase | Status | Target |
|---|---|---|
| Spec & architecture | ✅ Done | - |
| F1 - MVP (search + load, in-mem) | 🔄 In progress | T+1d |
| F2 - Production (hot-reload, HTTP, threat model) | ⏳ Planned | T+2d |
| F3 - Public release (PyPI, docs, FtF post) | ⏳ Planned | T+3d |
| F4 - Polish (telemetry, TUI, more backends) | ⏳ Backlog | post-1.0 |

See [`SPEC.md`](./SPEC.md) for full PRD. See [`docs/`](./docs/) for architecture deep dive, threat model, and onboarding.

---

## Acknowledgments / Prior art

This project stands on shoulders. Worth checking out:

- [Anthropic's Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) - the canonical pattern we mirror
- [`bobmatnyc/mcp-skillset`](https://github.com/bobmatnyc/mcp-skillset) - most mature prior art; their threat model is the reference implementation
- [`back1ply/agent-skill-loader`](https://github.com/back1ply/agent-skill-loader) - file-watcher patterns
- [`gotalab/skillport`](https://github.com/gotalab/skillport) - minimal search-then-load reference
- [`VoltAgent/awesome-agent-skills`](https://github.com/VoltAgent/awesome-agent-skills) - 1000+ skill corpus we benchmark against

What `skill-radar` does differently: 2-tool surface (mirroring Anthropic's pattern), Anthropic-aligned defaults, air-gapped friendly, multi-client by design.

---

## License

MIT (planned). See `LICENSE` once published.

---

## Author

Built by [Dariusz Kowalski](https://sdet.it) - SDET, accessibility advocate, context-engineering enthusiast.

Part of the **SDET ecosystem**: [sdet.it](https://sdet.it) · [cdat.sdet.it](https://cdat.sdet.it) · [brain.sdet.it](https://brain.sdet.it) (soon)
