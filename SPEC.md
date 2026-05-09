# skills-radar - Product Requirements & Design Spec

**Status:** Draft v0.1 - 2026-05-09
**Authors:** Dariusz Kowalski (SDET) + Claude (Opus 4.7)
**License:** MIT (planned)

---

## 1. Problem

Claude Code's native skill discovery loads **every installed skill's name + description** into the system prompt at session start. With 80+ skills (mix of user, project, and plugin scope), this consumes ~6,000 tokens **before the user types a single word**. The user's `/doctor` showed a 2.9% context budget hit; raising `skillListingBudgetFraction` is a stopgap, not a solution.

**Anthropic shipped MCP Tool Search Tool** (late 2025) for a sister problem (MCP tool bloat), achieving 85% token reduction and Opus 4.5 accuracy improving 79.5% → 88.1%. But **skills are a different mechanism** and Tool Search does not apply to them. The community has open feature requests (claude-code issues #16160, #19105) - no native fix shipped.

**Existing community attempts** (`bobmatnyc/mcp-skillset`, `back1ply/agent-skill-loader`, `gotalab/skillport`) each solve a slice but none combines: (a) Anthropic's own search-then-load pattern, (b) hot-reload, (c) trust-tiered threat model, (d) air-gapped install path, (e) multi-client (Claude Code + Cursor + Claude Desktop + custom agents).

## 2. Solution - one sentence

**`skills-radar`** is a local MCP server that exposes a 2-tool surface (`search_skills`, `load_skill`) so AI agents can discover Claude Code-style Skills via vector + BM25 hybrid retrieval instead of preloading metadata. Mirrors Anthropic's Tool Search Tool pattern. Threat-model-first. Air-gapped friendly.

## 3. Two-Tier Discovery Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ AGENT (Claude Code, Cursor, Claude Desktop, custom)              │
│                                                                  │
│ System prompt contains:                                          │
│  • Mini-index: name + 1-line summary (~1k tokens for 80 skills)  │
│  • 2 MCP tools from skills-radar                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
        Agent decides:     ▼
        ┌───────────────────────────────────────┐
        │ Is the skill name obvious from intent? │
        └───────┬───────────────────────┬───────┘
                │ YES                   │ NO / ambiguous
                ▼                       ▼
       load_skill(name)         search_skills(query, top_k=5)
                │                       │
                │                       ▼
                │              Top matches w/ score
                │              [{name, description, score}]
                │                       │
                │                       ▼ Agent selects best match
                ▼                       ▼
        ┌───────────────────────────────────────┐
        │ Full SKILL.md returned                │
        │ • Sanitized for injection              │
        │ • Trust tier annotated                 │
        │ • Bundled file index appended          │
        └───────────────────────────────────────┘
```

### Why two tiers

- **Tier 1 - Mini-index in system prompt** ensures Claude *knows the radar exists* and what's roughly available. Without it, Claude may never call MCP tools at all (the discovery dilemma). ~1k tokens - small price to pay for relevance.
- **Tier 2 - Full SKILL.md on demand** loads only the chosen skill's body when the agent commits to acting. Saves ~83% of typical token cost.

## 4. MCP Tool Surface (final, locked)

Only **two tools**. Anthropic's Tool Search Tool ships one; we ship two because skills are more discrete than tools (search ≠ load is meaningful for skills, less so for tools).

### `search_skills(query: str, top_k: int = 5, tags: list[str] | None = None) -> list[SkillMatch]`

Hybrid retrieval over (description + when_to_use), NEVER over body. Returns:

```json
{
  "matches": [
    {
      "name": "wcag-toolkit-lead",
      "description": "WCAG toolkit orchestrator - front door for sdet-wcag-toolkit operations.",
      "trust": "user",
      "score": 0.84,
      "scope": "project:/Users/dariusz/dev/darco81/sdet-wcag-toolkit"
    },
    ...
  ],
  "query_processed": "wcag accessibility audit",
  "total_indexed": 87
}
```

### `load_skill(name: str) -> SkillContent`

Fetches sanitized SKILL.md content. Returns:

```json
{
  "name": "wcag-toolkit-lead",
  "frontmatter": {...},
  "body_markdown": "...",
  "trust": "user",
  "bundled_files": ["./tools/wcag-runner.py"],
  "scope": "project:/Users/dariusz/dev/darco81/sdet-wcag-toolkit",
  "warnings": []
}
```

**Locked decisions:**
- No admin tools in the same MCP (refresh, stats, config) - separated into CLI.
- Tool descriptions stay under 200 chars (eat your own dogfood - these load into agent context).
- Returns structured output `(content_summary, structured_data)` per MCP SDK 2025-06-18 spec.

## 5. Threat Model - non-negotiable, day-one

Every ingested SKILL.md is treated as **adversarial input**. Skills are arbitrary instructions injected into a host agent's context; a malicious skill = system prompt injection.

### Trust tiers

| Tier | Source | Treatment |
|---|---|---|
| **TRUSTED** | Bundled `.skills-radar/builtin/` (project-vetted) | Pass through |
| **VERIFIED** | Signed registry (TBD), `~/.claude/plugins/cache/claude-plugins-official/` | Light sanitization, log |
| **USER** | `~/.claude/skills/`, project `.claude/skills/` (your own files) | Trusted local - light sanitization |
| **UNTRUSTED** | Anything else (e.g., dynamically registered paths) | Strict sanitization, blocked patterns rejected |

### Sanitization on ingest (all tiers)

- Reject reserved names ("anthropic", "claude")
- Strip XML-like instruction-override tags (`<system>`, `<override>`, `<jailbreak>`, etc.)
- Detect prompt-injection patterns (regex catalog, configurable)
- Enforce size limits (default 64KB per SKILL.md)
- Reject Windows path separators in `paths:` field
- Strip live-execution syntax (`` !`...` ``) for non-Claude-Code clients (configurable per-client)

### Trust signals exposed to agent

`load_skill` includes `trust` in response. Downstream agent can refuse to execute untrusted skills.

## 6. Tech Stack

| Layer | Default | Optional |
|---|---|---|
| **Runtime** | Python 3.11+ | - |
| **MCP SDK** | `mcp` (FastMCP) | - |
| **Transport** | Streamable HTTP (`stateless_http=True, json_response=True`) | stdio (local dev) |
| **Embedder** | `sentence-transformers/all-MiniLM-L6-v2` (90MB, CPU-fast) | `bge-small-en-v1.5`, MLX (Mac), OpenAI/Voyage (cloud) |
| **Lexical retrieval** | `rank_bm25` (BM25Okapi) | - |
| **Vector store** | ChromaDB (embedded, zero-deps, persistent) | Qdrant (advanced users) |
| **File watcher** | `watchdog` | - |
| **CLI** | `typer` + `rich` | - |
| **Config** | `pydantic-settings` + YAML | - |
| **Validation** | `pydantic` v2 | - |

**Why ChromaDB default (not FAISS+SQLite):** built-in metadata + persistence + no manual schema; matches `mcp-skillset` prior art; air-gapped path is single-file SQLite-backed store.

**Why hybrid retrieval (BM25 + dense):** Anthropic ships both variants of Tool Search; benchmarks consistently show 70/30 semantic+lexical beats either alone for short descriptions.

## 7. SKILL.md Frontmatter - what we support

Per Claude Code spec (May 2026), ingest accepts these fields:

| Field | Required | Indexed? | Notes |
|---|---|---|---|
| `name` | yes | yes | ≤64 chars, lowercase + hyphens |
| `description` | yes | yes | ≤1024 chars |
| `when_to_use` | no | yes | concatenated with description for retrieval |
| `argument-hint`, `arguments` | no | no | passthrough |
| `disable-model-invocation` | no | no | filtered from `search_skills` if true |
| `user-invocable` | no | no | passthrough |
| `allowed-tools` | no | no | **stripped for non-CLI clients** (CLI-only field) |
| `model`, `effort`, `context`, `agent`, `hooks` | no | no | passthrough |
| `paths` | no | metadata | used for scope filtering, not text-indexed |
| `shell` | no | no | passthrough |
| **`hub-tags`** ✨ | no | yes | **our extension** - list of categories for filtered search |

`hub-tags` is the only field we add. Backward-compatible (Claude Code ignores unknown frontmatter).

## 8. Phases

### Phase 1 - MVP (~3-4h)
- [ ] `pyproject.toml` + package skeleton
- [ ] `mcp_server.py` - FastMCP server with `search_skills` + `load_skill` tools (stdio transport)
- [ ] `indexer.py` - scan SKILL.md from configured paths
- [ ] `embedder.py` - sentence-transformers default, swappable
- [ ] `store.py` - ChromaDB wrapper
- [ ] `sanitize.py` - basic sanitization + trust tier assignment
- [ ] `cli.py` - `skills-radar serve | index | list | doctor`
- [ ] Manual smoke test against the user's `~/.claude/skills/`

### Phase 2 - Production-ready (~4-5h)
- [ ] `watcher.py` - watchdog-based hot-reload
- [ ] Streamable HTTP transport
- [ ] `mini_index.py` - auto-generate `~/.claude/SKILLS-INDEX.md`
- [ ] Trust tier full implementation (registry, signing TBD)
- [ ] Prompt-injection scanner (regex catalog + extensible)
- [ ] `tests/` - pytest, ≥70% coverage on core
- [ ] Docker image (pre-baked embedding model)
- [ ] `docs/architecture.md`, `docs/threat-model.md`, `docs/onboarding.md`

### Phase 3 - Public release (~3-4h)
- [ ] `README.md` - user-facing onboarding
- [ ] `CONTRIBUTING.md`
- [ ] GitHub Actions: lint + test + publish to PyPI on tag
- [ ] PyPI package
- [ ] `examples/` - sample skills, Claude Code config snippet, Cursor config
- [ ] **From the Field bonus episode** - EN + PL drafts (per memory rule)
- [ ] Public announcement + LinkedIn post

### Phase 4 - Polish (post-launch)
- [ ] Stats / telemetry (local, opt-in)
- [ ] TUI dashboard (`skills-radar tui`)
- [ ] MLX embedder (Mac only)
- [ ] Voyage / OpenAI embedder backends
- [ ] Auto-discovery from GitHub repos (e.g., `awesome-agent-skills`)

## 9. CLI Surface (final)

```
skills-radar serve [--transport stdio|http] [--port 6580]
skills-radar index [--rebuild] [--paths PATH...]
skills-radar list [--tag TAG] [--trust LEVEL]
skills-radar mini-index --output PATH
skills-radar doctor                    # sanity: paths, embedder, store, transport
skills-radar config show|edit
```

## 10. Config

`~/.config/skills-radar/config.yaml` (XDG-compliant):

```yaml
paths:
  - ~/.claude/skills
  - ~/.claude/plugins/cache/*/skills
  - .claude/skills        # project-relative, expanded per-cwd
  - ~/dev/**/.claude/skills

embedder:
  backend: sentence-transformers
  model: all-MiniLM-L6-v2

store:
  backend: chromadb
  path: ~/.local/share/skills-radar/store

transport:
  mode: stdio                # or 'http'
  http_port: 6580

retrieval:
  hybrid_weight_semantic: 0.7
  hybrid_weight_lexical: 0.3
  default_top_k: 5

trust:
  default_tier: user
  trusted_paths:
    - ~/.claude/skills
  blocked_patterns_file: ~/.config/skills-radar/blocked-patterns.txt

sanitization:
  max_skill_size_kb: 64
  strip_xml_tags: true
  reject_reserved_names: ["anthropic", "claude"]
```

## 10b. Deployment modes (added v0.3.0a2)

Two supported modes:

### Mode A - Docker Desktop running 24/7

Container running cały czas (`docker compose up -d`), every Claude Code session in every project connects to the same `http://localhost:6580/mcp`. Container has persistent ChromaDB volume, bind-mounted skill paths read-only, watcher on (baked config has `watcher.enabled: true`). One MCP registration per machine:

```bash
claude mcp add --transport http skills-radar http://localhost:6580/mcp
```

Tradeoff: cross-platform infrastructure, easy recovery, but Linux container can't reach Apple GPU → **no MLX path inside the container**. Stack inside is sentence-transformers + ChromaDB (+ optional Qdrant + Ollama if reachable from container).

### Mode B - Native install (100% local Apple Silicon MLX stack)

Bare-metal Python install, stdio subprocess per CC session, OR long-running HTTP server (launchd plist or `nohup` for "always running" parity with Docker). Full MLX path: embedder + rewriter + reranker. **Mac arm64 only.**

```bash
pip install 'skills-radar[mlx]'
skills-radar serve --transport http --watch &
claude mcp add --transport http skills-radar http://localhost:6580/mcp
```

### Watcher config (added v0.3.0a2)

- `watcher.enabled: bool = false` (default off)
- `watcher.debounce_ms: int = 250`
- CLI `--watch / --no-watch` overrides config

Watchdog uses kernel-level FS events (`kqueue` on macOS, `inotify` on Linux). Pasywny - ~8 MB stałego RAMu, 0 CPU gdy SKILL.md się nie zmienia. Recommended ON for Mode A (Docker baked config has `enabled: true`), opt-in for Mode B.

## 11. Public Release Plan

### Repo
- `github.com/sdet-it/skills-radar` (or personal `github.com/darco81/skills-radar`)
- License: **MIT**
- Branding: minimal, neutral - no SDET-specific lock-in

### PyPI
- Package: `skills-radar`
- Versioning: SemVer, start `0.1.0`
- Publish via GitHub Actions on git tag

### Documentation
- `README.md` - TL;DR, install, quickstart for Claude Code
- `docs/architecture.md` - Two-Tier Discovery deep dive
- `docs/threat-model.md` - trust tiers, sanitization
- `docs/onboarding.md` - step-by-step
- `docs/writing-skills.md` - how to write good SKILL.md (with `hub-tags`)
- `docs/context-engineering.md` - why this matters (Anthropic refs)

### Distribution targets
- PyPI primary
- Docker Hub (pre-baked model)
- Homebrew formula (later)

## 12. From the Field - Bonus Episode Outline

**Working title (EN):** *"My Claude Code prompt was bleeding 6000 tokens before I typed a word - here's the MCP server I built."*

**Working title (PL):** *"Mój prompt Claude Code zżerał 6000 tokenów zanim cokolwiek napisałem - oto serwer MCP, który zrobiłem żeby to naprawić."*

**Hook:**
- Open with `/doctor` screenshot showing the bleed
- Show Anthropic's Tool Search announcement → "they fixed tools. Skills are next, and nobody shipped it yet."
- Walk through Two-Tier Discovery in 60 seconds
- Demo: search → load → action
- Repo + 30-sec install
- Call to action: "drop your skill count, I'll guess your token bleed"

**Bilingual rule (per memory):** EN main post, PL link as first comment on LinkedIn.

**Optional:** demo video (terminal recording, ~90s), repo stars-bait section ("if this saved you tokens, star it").

## 13. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Anthropic ships native lazy skills | Medium | Our value: hot-reload, threat model, multi-client, telemetry. Stay differentiated. |
| ChromaDB heavy for some users | Low | Pluggable storage; can swap to FAISS+SQLite. |
| Embedding model 90MB blocks first-run | Low | Pre-bake into Docker; document `--offline` mode. |
| `bobmatnyc/mcp-skillset` overlap | Medium | Different positioning: theirs is heavy/feature-rich; ours is light/Anthropic-pattern-aligned. |
| SKILL.md as injection vector | High | Day-one threat model. |
| `allowed-tools` field SDK incompatibility | Medium | Strip on non-CLI client return. |
| Stdout pollution kills stdio transport | High | All logging to stderr; `print()` linter check. |

## 14. Definition of Done - v0.1.0 Release

- [ ] `skills-radar serve` connects to Claude Code via `.mcp.json` config
- [ ] User can drop a SKILL.md into `~/.claude/skills/foo/` and within 1s `search_skills("foo topic")` returns it
- [ ] `load_skill("foo")` returns sanitized content with trust tier
- [ ] All Anthropic gotchas from research handled (stdout, allowed-tools strip, name reserved, paths, size limit)
- [ ] Tests passing, ≥70% coverage on core modules
- [ ] README + 3 docs files complete
- [ ] PyPI release `0.1.0`
- [ ] From the Field bonus draft (EN + PL) ready to publish

## 15. Open Questions

1. **Repo home** - `github.com/sdet-it/skills-radar` (org) or `github.com/darco81/skills-radar` (personal)?
2. **Trust registry** - for VERIFIED tier, do we host a JSON manifest in repo, or punt to v0.2?
3. **Tag taxonomy** - should we publish a recommended `hub-tags` vocabulary (`a11y`, `perf`, `content`, `dev`, `qa`, ...) or let community converge?
4. **Telemetry** - local-only opt-in stats from start, or post-1.0?

---

*This is a living document. Edit as decisions are made. Each phase ships a tagged version: v0.1.0 (MVP), v0.2.0 (production), v0.3.0 (public release).*
