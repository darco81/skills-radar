# 📡 skills-radar

> **Lazy-loading skill discovery for Claude Code (and other MCP clients).**
> Stop bleeding context tokens on skills you might never use.

`skills-radar` is a local **MCP server** that mirrors Anthropic's [MCP Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) pattern - but for **Skills**. Instead of preloading every skill's metadata into the system prompt at session start (default Claude Code behavior), `skills-radar` exposes two tools (`search_skills`, `load_skill`) so the agent fetches only what's relevant to the current task.

**Why this exists:** Anthropic shipped Tool Search for MCP tools in late 2025 (85% token reduction, +8.6% accuracy on Opus 4.5). They haven't shipped the equivalent for Skills yet. With 80+ skills across personal, project, and plugin scopes, your `/doctor` is probably bleeding 5-10k tokens before you type a word. This fixes that.

> **Status:** 🚧 v0.1 in active development. Spec: [`SPEC.md`](./SPEC.md). MVP target: ~3-4h after spec approval.

---

## Two deployment modes

Pick one based on your workflow:

### Mode A - Docker Desktop running 24/7 (recommended for shared / cross-platform / Linux / Windows)

One container, every Claude Code session in every project connects to the same `http://localhost:6580/mcp`. Container has persistent ChromaDB volume + bind-mounted skill paths read-only + watcher on (baked config). Healthy in ~1 second after `docker compose up`.

```bash
git clone https://github.com/dar-kow/skills-radar
cd skills-radar
docker compose up -d --build

claude mcp add --transport http skills-radar http://localhost:6580/mcp
# Restart Claude Code - /mcp shows skills-radar connected.
```

Pros: one moving piece, recoverable via `docker compose restart`, runs on Linux/Windows/macOS, isolated. **Limitation on macOS:** no MLX inside the container (Linux container can't reach the Apple GPU). Use Mode B for the full MLX stack.

### Mode B - Native install (recommended for the 100% local Apple Silicon MLX stack)

stdio subprocess per Claude Code session, OR a long-running HTTP server.

```bash
pip install 'skills-radar[mlx]'                # MLX extras for Apple Silicon
skills-radar config-init
skills-radar index

# stdio (auto-starts per CC session):
claude mcp add skills-radar -- skills-radar serve --transport stdio --watch

# OR HTTP, long-running (Mode A behavior natively, with MLX):
skills-radar serve --transport http --watch &
claude mcp add --transport http skills-radar http://localhost:6580/mcp
```

Pros: full MLX rewriter + reranker on Apple Silicon (4096-dim Qwen3 embedder, MoE Qwen3-Coder for rerank), zero Ollama, zero network. **Mac arm64 only.**

### Recovering token budget (both modes)

```json
{ "skillOverrides": { "*": "name-only" } }
```

Now Claude only sees skill **names** in the prompt (~1k tokens for 80 skills), and queries `skills-radar` for full descriptions when needed.

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
- 🔥 **Hot reload** - drop a SKILL.md, indexed in <1s via `watchdog` (no Claude restart)
- 🛡️ **Threat model day-one** - trust tiers (TRUSTED / VERIFIED / USER / UNTRUSTED), prompt-injection scanning, size limits, XML-injection stripping
- 🪶 **Light by default** - sentence-transformers (90MB) + ChromaDB (zero deps)
- 🔌 **Pluggable** - swap embedder (sentence-transformers, MLX [planned], Voyage [planned], OpenAI [planned]); swap store (ChromaDB default, Qdrant [planned])
- 🌐 **Multi-client** - Claude Code, Cursor, Claude Desktop, custom MCP agents
- 📡 **Streamable HTTP** transport (`stateless_http=True, json_response=True`) for production; stdio for local dev
- 🤖 **Optional local-LLM query rewriter** (Ollama) - rewrites ambiguous queries into richer keyword phrases before embedding
- ✈️ **Air-gapped friendly** - pre-baked Docker image, offline HF Hub flags
- 🧪 **2-tool MCP surface** - `search_skills` + `load_skill`. Mirrors Anthropic's Tool Search Tool pattern. Eats own dogfood: tool descriptions stay under 200 chars.

---

## Production deployment

For shared / multi-client / Docker deployments, run the **Streamable HTTP** transport instead of stdio.

### Bare-metal

```bash
skills-radar serve --transport http --host 0.0.0.0 --port 6580 --watch
```

Defaults match MCP Python SDK guidance: `stateless_http=True`, `json_response=True` - pair both for horizontal scaling behind a load balancer.

### Docker

```bash
docker compose up -d --build
```

The bundled Dockerfile pre-bakes the embedding model so containers start in ~2s instead of doing a 30-60s first-run download. Defaults to non-root uid 1000, offline HF Hub flags, strict sanitization (UNTRUSTED tier + `strip_live_exec=true`) - community skills mounted via Docker shouldn't be allowed to run host-level commands.

`docker-compose.yml` mounts your `~/.claude/skills` and plugin cache read-only and persists the ChromaDB store as a named volume.

### Verify

```bash
curl -X POST http://127.0.0.1:6580/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json,text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"client","version":"0.1.0"}}}'
```

Should return `200 OK` with the server capabilities + tool list.

---

## Local-LLM query rewriter (optional, opt-in)

If you have [Ollama](https://ollama.com/) running locally, you can have it rewrite ambiguous queries (especially multi-language ones) into richer English keyword phrases before they hit the embedder. Big quality boost for free.

```yaml
# ~/.config/skills-radar/config.yaml
retrieval:
  rewriter:
    enabled: true
    backend: ollama
    model: gemma4:e4b      # or any small local model with low latency
    url: http://localhost:11434
    timeout: 5.0
```

Resilient by design: any HTTP error, timeout, or parse failure falls back to the raw query. Off by default - search works exactly as before unless you opt in.

---

## Project status

| Phase | Status | Tag |
|---|---|---|
| Spec & architecture | ✅ Done | - |
| F1 - MVP (search + load, in-mem) | ✅ Done | `v0.1.0a0` |
| F2 - Production (hot-reload, HTTP, threat model, Docker, integration tests) | ✅ Done | `v0.2.0` |
| F3 - Public release (PyPI, GitHub Actions, FtF post) | 🔄 In progress | - |
| F4 - Polish (MLX backend, telemetry, TUI, more backends) | ⏳ Backlog | post-1.0 |

See [`SPEC.md`](./SPEC.md) for full PRD. See [`docs/`](./docs/) for architecture deep dive, threat model, writing-skills guide, context engineering rationale, and onboarding.

---

## Acknowledgments / Prior art

This project stands on shoulders. Worth checking out:

- [Anthropic's Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) - the canonical pattern we mirror
- [`bobmatnyc/mcp-skillset`](https://github.com/bobmatnyc/mcp-skillset) - most mature prior art; their threat model is the reference implementation
- [`back1ply/agent-skill-loader`](https://github.com/back1ply/agent-skill-loader) - file-watcher patterns
- [`gotalab/skillport`](https://github.com/gotalab/skillport) - minimal search-then-load reference
- [`VoltAgent/awesome-agent-skills`](https://github.com/VoltAgent/awesome-agent-skills) - 1000+ skill corpus we benchmark against

What `skills-radar` does differently: 2-tool surface (mirroring Anthropic's pattern), Anthropic-aligned defaults, air-gapped friendly, multi-client by design.

---

## License

MIT (planned). See `LICENSE` once published.

---

## Author

Built by [Dariusz Kowalski](https://sdet.it) - SDET, accessibility advocate, context-engineering enthusiast.

Part of the **SDET ecosystem**: [sdet.it](https://sdet.it) · [cdat.sdet.it](https://cdat.sdet.it) · [brain.sdet.it](https://brain.sdet.it) (soon)
