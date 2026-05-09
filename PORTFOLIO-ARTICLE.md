# skills-radar - portfolio case study draft

> **Format:** standalone case study for portfolio.sdet.it. Not a From the Field episode. ~2500 words EN. Voice: peer-level senior engineers, no corporate-speak.
> **Status:** draft v1 - needs voice pass + screenshot insertion before publication.
> **Repo:** `github.com/darco81/skills-radar` (push pending Claude Desktop decision)

---

# Building a lazy-loading skill discovery layer for Claude Code

## Hook

I ran `/doctor` in Claude Code on a Friday morning. Before I'd typed a single character, my prompt was 6,000 tokens deep. That's not the model thinking. That's not my project context. That's just **skill descriptions** - every installed skill across personal, project, and plugin scopes, preloaded into the system prompt at session start.

I had ~80 skills. Not because I was hoarding them - Claude Code's marketplace makes installing skills frictionless, and a sprawling skill library is genuinely useful. The cost is invisible until you measure it.

This is the story of how I built `skills-radar` - an open-source MCP server that fixes the problem - in a single day, why the obvious approach doesn't work, and what the production-grade solution actually requires.

## The thing nobody fixed

Late 2025, Anthropic shipped **Tool Search Tool** for the API. Tools marked `defer_loading: true` are invisible until Claude calls a built-in `tool_search_tool`. Their internal numbers: 85% token reduction, Opus 4.5 accuracy 79.5% → 88.1% on large tool libraries. They shipped the same idea for MCP servers in Claude Code shortly after.

But Tool Search is for **MCP tools**. Skills are a different mechanism - files in `~/.claude/skills/`, loaded via the Skill tool, not via MCP. Anthropic hasn't shipped the equivalent for skills yet. GitHub issues #16160 and #19105 sit open.

So I built it. Not because nobody else has tried - there are several `mcp-skill-server` projects in the wild - but because **none of them solve the core problem**.

## The discovery dilemma

Naive RAG over skills fails at the first hurdle:

> If the agent doesn't see the skills exist, it never queries the index. If it never queries the index, the lazy loading is pointless.

Most community projects ship a single MCP tool - `find_relevant_skill` - and assume Claude will query it on every turn. It doesn't. Without a Tier-1 surface signal telling the agent *"these skills exist and roughly do X, Y, Z"*, Tier-2 retrieval is invisible. The MCP server stays unused.

This is the lesson I learned from reading prior art (`bobmatnyc/mcp-skillset`, `back1ply/agent-skill-loader`, `gotalab/skillport`). Each got pieces right, but none combined: (a) Anthropic's own search-then-load pattern, (b) hot-reload, (c) trust-tiered threat model, (d) air-gapped install path, (e) multi-client support.

## Two-Tier Discovery - the architecture

`skills-radar` splits discovery in two complementary signals:

**Tier 1 - Mini-index, ~1k tokens, always preloaded.** A flat list of `name + 1-line summary` per skill, written to `~/.claude/SKILLS-INDEX.md` and imported into the global `CLAUDE.md`. Tells the agent *what exists*.

**Tier 2 - On-demand load via MCP.** Two tools:
- `search_skills(query, top_k=5, tags=None)` - hybrid retrieval (BM25 + dense embeddings, 70/30 weighted) over `description + when_to_use`. Returns ranked matches with name / description / trust / score / scope.
- `load_skill(name)` - full sanitized SKILL.md when the agent commits to acting.

Body of SKILL.md is **never** indexed for retrieval - only loaded on `load_skill`. This keeps the index small, focused, and accurate.

Result on my own 60-skill corpus: **6,000 tokens → 1,900 tokens preloaded**. ~68% reduction. The cost stays roughly flat as you scale to 500 skills.

Why two tools, not one? Because skills are more discrete than tools. When a user says "use wcag-toolkit-lead", the name is obvious - call `load_skill` directly. When they say "audit my a11y", the intent is fuzzy - call `search_skills` first. Anthropic's Tool Search ships one tool because tools are typically called by exact name; skills earn the second tool because their use is more declarative.

## Threat model - non-negotiable, day-one

A SKILL.md file is loaded directly into a host agent's context window as instructions. From the model's perspective, the difference between a system prompt and a skill body is mostly nominal - both shape behavior. **A malicious skill is a system-prompt injection vector.**

Common attack surfaces:
1. **Open-source skill collections** (e.g., the 1000+ in `awesome-agent-skills`) - anyone can submit, quality control varies
2. **Plugin marketplaces** - a hijacked maintainer account ships a malicious skill
3. **Project-cloned skills** - clone a repo, suddenly its `.claude/skills/` are part of your scan paths
4. **Your own future mistakes** - paste something you didn't sanity-check

Naive RAG loads any of these as authoritative instructions. We refuse to do that.

skills-radar ships four layers of defense, applied at ingest:

**Trust tier assignment.** Every skill is tagged at ingest with TRUSTED (config-explicit) > VERIFIED (Anthropic-official plugin cache) > USER (~/.claude/skills) > UNTRUSTED (anything else). Tier surfaced in `load_skill` response so downstream agents can refuse UNTRUSTED.

**Frontmatter validation.** Reserved-word rejection (`anthropic`, `claude`), name format (≤64 chars, lowercase + hyphens), required fields, max size 64KB.

**Body sanitization.** XML injection tag stripping (`<system>`, `<override>`, `<jailbreak>`, ...), prompt-injection regex catalog (configurable), optional live-execution syntax stripping for non-Claude-Code clients.

**Size cap.** UTF-8 byte-length cap per SKILL.md. Skills exceeding the cap are rejected entirely.

These don't make community skills safe to run blindly - they make them **measurable**, with surface-area visible to the agent. Combined with explicit trust tiers, downstream agents can implement policies like "refuse UNTRUSTED skills by default; require explicit user opt-in".

## Tech stack - three paths, one repo

The default install runs cross-platform on a single machine. Two optional paths add power: a 100% local Apple Silicon stack (zero network, zero cloud, zero Ollama), and a cross-platform LLM-augmented stack via Ollama.

| Layer | Default (cross-platform) | Mac 100% local (MLX) | Cross-platform LLM (Ollama) |
|---|---|---|---|
| Runtime | Python 3.11+ | - | - |
| MCP SDK | `mcp` (FastMCP) | - | - |
| Transport | stdio (Claude Code) / Streamable HTTP (production) | - | - |
| **Embedder** | `sentence-transformers/all-MiniLM-L6-v2` (90 MB, 384-dim, CPU-fast) | **MLX `Qwen3-Embedding-8B-4bit-DWQ`** (4096-dim, Apple Silicon) | - |
| Lexical | BM25 via `rank_bm25` | - | - |
| **Vector store** | ChromaDB (embedded, zero deps) | **Qdrant** (production, reusable across projects - share an instance with sdet-brain) | Qdrant |
| File watcher | `watchdog` 250 ms debounce | - | - |
| **Query rewriter** | NoOp | **MLX `Qwen3-Coder-30B-A3B-Instruct-4bit`** - lazy load + LRU cache | Ollama (`gemma4:e4b`), HTTP fallback |
| **Reranker** | NoOp | **MLX `Qwen3-Coder-30B-A3B`** - single-pass batch scoring | Ollama, per-pair scoring |
| Telemetry | Off (strict opt-in) | Same | Same |

Why this exact split: defaults are **light** (90 MB model, zero infrastructure) so the open-source community can install with `pip install skills-radar` and run immediately. Two power-user paths are **opt-in** so they don't bloat the base install but are wired up cleanly when you flip the config flags.

The **100% local Apple Silicon stack** is the design highlight. Set:

```yaml
embedder:
  backend: mlx
  model: mlx-community/Qwen3-Embedding-8B-4bit-DWQ
retrieval:
  rewriter:
    enabled: true
    backend: mlx
    model: mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
  reranker:
    enabled: true
    backend: mlx
    model: mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
```

…and the entire pipeline - embedding, query rewriting, reranking - runs on your M-series GPU + Neural Engine. No Ollama. No HTTP. No network. Repeated identical queries hit a per-instance LRU cache; warm queries cost ~3 seconds in an MCP server (model in memory) instead of 6+ on cold CLI invocations.

## Quality of retrieval - the numbers that matter

The Polish fuzzy query is the cleanest demonstration of the tradeoff. Same 60-skill corpus, same query, three configurations:

**Query:** `napisz mi post na LinkedIn o WCAG` (mixed-language, ambiguous intent - could be "write a LinkedIn post about WCAG" or "find me a WCAG-related skill").

| Config | Top 5 (name, score) | Verdict |
|---|---|---|
| Default sentence-transformers, NoOp rewriter | content-writing-lead (0.54), **ffcss-migrate (0.49 false positive)**, wcag-toolkit-lead (0.42), wcag-dynamic-test (0.32), wcag-report (0.29) | top-1 correct but margin razor-thin; #2 is a coincidental Tailwind→FFCSS migration skill |
| Default + Ollama rewriter (gemma4:e4b) | content-writing-lead (cleaner top), other a11y skills surface | margin widens, +100-300 ms latency |
| **MLX rewriter (Qwen3-Coder-30B-A3B-Instruct-4bit)** | a11y-audit (**0.71**), a11y-orchestrator (0.65), a11y-fix (0.61), wcag-static-analyze (0.56), wcag-fix (0.44) | **all 5 hits are a11y/WCAG**, top-1 above 0.7, ~9 s on CLI cold / ~3 s warm in MCP server |

Two things to notice. First - the rewriter doesn't preserve the original surface intent. With MLX rewriter on, `content-writing-lead` doesn't appear at all. The rewriter normalized "post o WCAG" to keywords like *web accessibility wcag accessibility standards accessibility standards* - which is fine for "find me a WCAG-related skill" intent, but a miss if you actually wanted writing help. Tradeoff is real and documented; rewriter is **off by default**.

Second - for English technical queries, the default backend is already solid (top-1 above 0.6 with clean separation). The MLX stack pays off mainly for fuzzy / multilingual / casual phrasing where the small embedder struggles. If your team writes queries in English engineering speak, you might never need the MLX path. If you're me and half your prompts are Polish, the MLX stack is the difference between "good enough most of the time" and "right every time."

## Local opt-in usage telemetry

I added a SQLite event log at `~/.local/share/skills-radar/stats.db`. Three event kinds - search, load, index - each with relevant fields (latency_ms, top1_score, trust tier, etc.). Strict opt-in: default disabled, no remote telemetry ever.

The `skills-radar stats` CLI surfaces:
- **Top loaded skills** (most actually fetched, not just searched - strong signal of usefulness)
- **Top queries** with frequency
- **Miss rate** - searches where top-1 score < 0.4 (calibrated from observation: below this, ranking is unreliable)
- **Recent events** with per-event detail

A miss rate above 30% is the signal to enable the Ollama rewriter or upgrade to MLX. Below 15%, the default stack is good enough.

## TUI dashboard

`skills-radar tui` starts a `rich.Live` real-time read-only dashboard with four panels:

```
┌─ skills-radar v0.3.0a0 · 60 skills · 5/5 paths · embedder=mlx · store=qdrant ─┐
├─ Trust tier breakdown ────────────────────────────────────────────────────────┤
│ TRUSTED    ████████░░░░░░░░  31                                                │
│ VERIFIED   ███████████░░░░░  38                                                │
│ USER       ░░░░░░░░░░░░░░░░   0                                                │
├─ Top queries · miss 12% of 17 ─┬─ Recent events · live ─────────────────────┤
│ wcag accessibility audit    3  │ 18:42  search  0.79  wcag audit  (132ms)    │
│ napisz post na linkedin     2  │ 18:41  load    perf-vue-runtime  (48ms)     │
│ vue memory leak             2  │ 18:40  search  0.67  vue memory leak  ...   │
├─ Top loaded skills ────────────┤                                              │
│ a11y-orchestrator           4  │                                              │
│ perf-vue-runtime            3  │                                              │
│ content-writing-lead        2  │                                              │
└────────────────────────────────┴──────────────────────────────────────────────┘
```

Recent events stream is color-coded: green for top-1 ≥ 0.6, yellow ≥ 0.4, red < 0.4. The miss-rate badge in the top-queries panel uses the same scheme. You can have this open on a second monitor while you work and watch the search quality in real time - invaluable for tuning hub-tags or deciding when to enable the rewriter.

## Hot reload

`watchdog` watches all configured paths. Each created / modified / deleted / moved SKILL.md triggers a single-record update in the index, debounced 250 ms to coalesce editor save bursts. Add a new SKILL.md, save, query through Claude Code immediately - no restart, no reindex command.

This is the differentiator vs every prior art I evaluated. Nobody else gets it right. `back1ply/agent-skill-loader` gets close but uses substring search that doesn't scale. `bobmatnyc/mcp-skillset` doesn't have it.

## Production deployment

For shared / multi-client / Docker deployments, `skills-radar serve --transport http` runs Streamable HTTP per MCP Python SDK guidance: `stateless_http=True, json_response=True` for horizontal scalability behind a load balancer.

The bundled `Dockerfile` is multi-stage: builder stage installs deps and pre-bakes the embedding model so the runtime stage starts in ~2 seconds instead of doing a 30-60 second first-run model download. Runtime is non-root (uid 1000), with offline HF Hub flags so it works in air-gapped environments. Defaults inside the container are strict: UNTRUSTED tier + `strip_live_exec=true` - community skills mounted via Docker shouldn't be allowed to run host-level commands.

`docker-compose.yml` mounts your `~/.claude/skills` and plugin cache read-only and persists the ChromaDB store as a named volume. Healthcheck POSTs a real MCP `initialize` handshake (not just GET - Streamable HTTP requires JSON-RPC body) and reports healthy in ~1 second.

## What I'd do differently

Four things, in retrospect:

1. **Start with the threat model, not the retrieval.** I wrote sanitization day one but spent 60% of effort on retrieval first. The retrieval problem is interesting; the threat model is what makes the tool actually deployable. If I were starting over I'd write `sanitize.py` and `trust tiers` first, tests for both, then build retrieval on top.

2. **Test BM25 before assuming hybrid is necessary.** My intuition was that pure BM25 would miss too many semantic matches. With short technical descriptions (50-300 chars), BM25 alone gets you 70-80% of the way. The hybrid retrieval pays for itself only in fuzzy / multilingual queries. For a hyper-minimal version, BM25-only would have shipped a week earlier.

3. **The `disable-model-invocation: true` flag is more useful than I initially thought.** Skills marked manual-only get filtered from `search_skills` automatically - turns out a non-trivial fraction of skills are templates / reference docs that shouldn't auto-trigger. Honoring this flag from day one is cheap; retrofitting is annoying.

4. **MLX latency is the wrong thing to optimize prematurely.** First-pass MLX rewriter implementation went straight for "score every candidate one at a time" pattern (mirroring Ollama). For a 20-candidate rerank, that's 20 separate inferences - minutes per query. Single-pass batch (one prompt enumerating all candidates, model returns `N=score` lines, parse with regex) collapses it to one inference, ~5-15 s for the whole pool. Cost: a regex parser. Reward: usable latency. Same lesson applies elsewhere - when working with local LLMs, **batch as much as the context window allows** before you start tuning model size.

## Scale economics

For a user with 80 skills:

| Strategy | Per-session cost | Worst case (use 1 skill) |
|---|---|---|
| Native Claude Code skill listing | ~6,000 tokens | ~6,000 tokens |
| skills-radar Two-Tier Discovery | ~1,000 tokens (mini-index) | ~1,000 + ~2,000 = ~3,000 tokens |
| skills-radar - multiple loads (5 skills) | ~1,000 + 5 × 2,000 = ~11,000 tokens | (rare - most sessions load 0-2) |

Net: in the realistic case (1-2 skills loaded per session), skills-radar saves ~3-5k tokens per session. At scale (500 skills), the native approach becomes unworkable; skills-radar's cost stays roughly flat.

This isn't just a cost story - it's a **quality** story. Anthropic's research on transformer attention shows that long context degrades response quality. A leaner prompt gives the model a fighting chance to stay focused.

## What's open

Several pieces consciously left for the next milestone:

- **FAISS store backend.** Lighter than ChromaDB (one file, zero schema), useful as fallback for restrictive environments where embedding even a SQLite-backed vector DB is too much.
- **Voyage / OpenAI embedder backends.** Cloud BYOK option for power users who want best-in-class embedding quality without a local 4 GB model.
- **Auto-discovery from GitHub repos** (e.g., `awesome-agent-skills`). One CLI command pulls a public skill collection into the UNTRUSTED tier with explicit per-skill confirm.
- **Crypto signing for VERIFIED tier.** Today VERIFIED is path-based (Anthropic-official plugin cache). Cryptographically signed skills with a trust manifest is the natural next step for community skill ecosystems.
- **LLM-based prompt-injection scanner.** Extends the regex catalog. A small local model (e.g. `gemma4:e4b` via Ollama) classifies suspicious bodies that the regex misses. Opt-in.
- **Sandbox `bundled_files`.** Today bundled files are enumerated in the `load_skill` response. A future version could optionally read-only sandbox files referenced one level deep so agents can pull them safely.
- **Multi-language hub-tags taxonomy.** Recommended `hub-tags` vocabulary (`a11y`, `perf`, `qa`, etc.) needs to be published and adopted to make filtered search useful at corpus scale.

## Repo + install

```bash
pip install skills-radar
skills-radar config-init
skills-radar index
claude mcp add skills-radar -- skills-radar serve --transport stdio --watch
```

Restart Claude Code. `/mcp` shows skills-radar connected. Run `skills-radar mini-index` and import `~/.claude/SKILLS-INDEX.md` into your global `CLAUDE.md`. That's the full setup.

Source: **github.com/darco81/skills-radar**. MIT license. Built one Friday in May 2026 between other things.

## Notes for self before publishing

- Insert real `/doctor` screenshot showing the bleed (`6000 tokens`)
- Insert TUI screenshot for the dashboard section (use `render_snapshot()` test path)
- Insert ranking comparison table screenshot (run actual queries, paste real numbers)
- Decide which portfolio category - devtools / open-source / case-study
- Cross-link from sdet.it main page case-study list
- This is a portfolio entry, not a From the Field episode - no PL version unless ROI changes
