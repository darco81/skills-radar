# Changelog

All notable changes to skills-radar are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned for v0.3.0 (first public)
- PyPI publish via GitHub Actions release workflow
- Portfolio standalone case study (EN, ~1500-3000 words) at portfolio.sdet.it
- README install GIF / demo screencast

### Planned for v0.4.0 / post-1.0
- Native MLX reranker (today: Ollama backend; MLX placeholder raises NotImplementedError)
- Voyage / OpenAI embedder backends
- FAISS store backend (zero deps fallback)
- Auto-discovery from GitHub repos (e.g., `awesome-agent-skills`)
- Crypto signing for VERIFIED tier
- LLM-based prompt-injection scanner (extends regex catalog)

## [v0.5.0a0] - 2026-06-10

### Added - conditional activation (Hermes-inspired)

Adopted from analysis of Nous Research's Hermes Agent skill routing (`agent/prompt_builder.py`): the only harness-side engineering in its model-pick architecture is deterministic pre-filtering of the skill index. skills-radar now does the same, one layer deeper (index time, not prompt-build time):

1. **`metadata.radar.*` frontmatter namespace** - conditional activation fields per the agentskills.io convention (mirrors Hermes' `metadata.hermes.*`), with top-level fallback: `platforms`, `requires_tools`, `fallback_for_tools`. `hub-tags` is also readable from the namespace now.
2. **Platform gating at index time** - skills declaring `platforms: [macos]` are skipped during reindex/hot-reload on non-matching hosts. New top-level config field `platform` ("" = auto-detect from `sys.platform`; Docker deployments must set it explicitly - the container reports `linux`).
3. **Tool conditions exposed in search results** - `requires_tools` / `fallback_for_tools` returned per match in `search_skills` (not filtered server-side; the server can't know the client's toolset - same agent-side policy contract as `trust`).
4. **Recall-bias instruction in mini-index header** - Hermes-style "if even partially relevant... err on the side of checking" nudge, addressing the weakest point of retrieval-first routing: the agent must decide to search at all.

### Fixed

- **Qdrant list-metadata crash** - `_csv_to_list` (mcp_server, mini_index) and `_split_tags` (app) assumed ChromaDB's CSV-string coercion; Qdrant keeps lists as-is in payload, so any skill with `hub-tags` would crash `search_skills` tag handling on the Qdrant backend. All three helpers now accept both shapes. Review pass caught a fourth instance: `skills-radar list --tag` (cli.py) had the same raw `.split(",")` - now routed through `_split_tags`.
- **Bare-scalar conditional fields fail-closed** - `platforms: macos` (natural YAML, not a list) was silently treated as "no constraint"; scalars now coerce to single-item lists so the gate actually gates.

## [v0.4.0a0] - 2026-05-09

### Added - F5 backlog complete

All 8 backlog items shipped in a single alpha:

1. **Hub-tags taxonomy** (`docs/hub-tags-taxonomy.md`) - recommended canonical 12: `a11y`, `perf`, `qa`, `dev`, `content`, `ml`, `ux`, `devops`, `docs`, `infra`, `sec`, `ops`. Per-tag definition + real corpus examples + how-to-apply rules + anti-patterns table + skills-radar consumption (filtered search, mini-index grouping) + future evolution rules + migration path.

2. **Sandbox bundled_files** (`src/skills_radar/sandbox.py`) - `load_skill(name, sandbox=True)` reads bundled files (one level deep from SKILL.md) with safe-extension whitelist, per-file + total size caps, path-traversal rejection, symlink rejection, UTF-8 decode validation. Same sanitization pipeline as SKILL.md body. 12 new tests.

3. **LLM injection scanner** (`src/skills_radar/injection_scanner.py`) - optional second-layer classifier that complements the regex catalog with a small local LLM (Ollama or MLX). Three backends: `none` (default), `ollama`, `mlx`. Robust JSON extraction with regex fallback. Resilient: any error degrades to "safe" (regex catalog already ran). 13 new tests.

4. **FAISS store backend** (`src/skills_radar/faiss_store.py`) - third pluggable vector store. FAISS IndexFlatIP with L2-normalized vectors (cosine equiv). Single dir with `faiss.index` + `meta.json`, no SQLite, no network. Tombstone-based delete. ~30 MB faiss-cpu wheel - lightest backend. Live-verified end-to-end.

5. **OpenAI embedder** (`src/skills_radar/embedder.py::OpenAIEmbedder`) - cloud BYOK via OPENAI_API_KEY. Default model `text-embedding-3-small` (1536-dim, ~$0.02 / 1M tokens). Excellent multilingual quality.

6. **Voyage embedder** (`src/skills_radar/embedder.py::VoyageEmbedder`) - cloud BYOK via VOYAGE_API_KEY. Default `voyage-3-lite` (512-dim). Specialized for retrieval, outperforms text-embedding-3 on most public benchmarks. Uses Voyage's distinct `input_type` for queries vs documents.

7. **GitHub auto-discovery** (`src/skills_radar/github_import.py` + CLI) - `skills-radar import-github org/repo` shallow-clones a public repo, finds SKILL.md files, copies them to `~/.local/share/skills-radar/imported/<org>--<repo>/...` (UNTRUSTED tier). Supports `--branch`, `--subpath`, `--yes`, `--dry-run`. Library mode requires explicit yes=True or dry_run=True for safety. Live-verified against `anthropics/skills` (18 candidate SKILL.md files listed in dry-run).

8. **Crypto signing for VERIFIED tier** (`src/skills_radar/signing.py`) - Ed25519 sign/verify path. SKILL.md signed → `SKILL.md.sig` JSON sidecar with `{version, key_id, algo, content_hash, signature}`. Verifier validates signature against trust_roots dict (key_id → base64 raw public-key bytes). Independent of the path-based VERIFIED tier (which still works for plugin cache); now any signed skill at any path can promote to VERIFIED. 7 new tests covering generate / sign / verify round-trip, missing sig, unknown key, hash mismatch (tamper detection), bad signature with wrong key, bad JSON in sig file. Opt-in via `[signing]` extras (cryptography>=42).

### Changed
- `make_embedder()` factory now dispatches: `sentence-transformers` / `mlx` / `openai` / `voyage`. ValueError on unknown backend lists all options with extras hint.
- `_make_store()` factory dispatches: `chromadb` / `qdrant` / `faiss`.
- `make_scanner()` factory dispatches: `none` / `ollama` / `mlx`.
- `pyproject.toml` extras: `mlx`, `qdrant`, `voyage`, `openai`, `faiss`, `signing` - every cloud / heavy-deps backend is opt-in.

### Tests
**95/95 pass** (88 prior + 7 signing) - ruff clean, format clean. Coverage 43%.

## [v0.3.0a2] - 2026-05-09

### Added
- **Watcher config option** - `watcher.enabled: bool = false` and `watcher.debounce_ms: int = 250` in config. CLI `--watch / --no-watch` overrides config. Fix for Docker baked config: container starts with `watcher.enabled: true` so hot-reload works without explicit CLI flag (the container CMD doesn't pass `--watch`).
- **Two deployment modes documented** in README and SPEC §10b:
  - **Mode A - Docker Desktop running 24/7** (recommended for cross-platform / shared / Linux / Windows). One container, every Claude Code session in every project connects to `http://localhost:6580/mcp`. Persistent ChromaDB volume, watcher on. Mac caveat: no MLX inside Linux container.
  - **Mode B - Native install** (recommended for 100% local Apple Silicon MLX stack). stdio per-session OR long-running HTTP. Full MLX path (embedder + rewriter + reranker), zero Ollama, zero network.

### Changed
- `run_stdio` and `run_http` accept `watch: bool | None = None` (was `bool = False`). `None` reads config; `True/False` is explicit override.
- Dockerfile baked config has `watcher.enabled: true` for the running-24/7 use case.

### Fixed
- `run_http` referenced `app` before definition (broken in v0.3.0a1 when wiring `_resolve_watch(watch, app)`). Now `app = _get_app()` at the top of `run_http`.

### Verified
- Container rebuild with `--no-cache` → healthy in 10s, `tools/call search_skills('WCAG audit')` returns a11y-orchestrator (top hit) over HTTP.
- User-scope MCP registration: `claude mcp add --scope user --transport http skills-radar http://localhost:6580/mcp` → ✓ Connected, available in every project.

## [v0.3.0a1] - 2026-05-09

### Added
- **MLX-native query rewriter** (`MLXRewriter`) - 100% local on Apple Silicon. Default model `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit` (MoE, 3B active). Lazy load + LRU cache (256 entries). `_dedupe_trailing` helper trims repeated keywords. Mac-only.
- **MLX-native reranker** (`MLXReranker`) - replaces v0.3.0a0 placeholder. Single-pass batch scoring: one prompt enumerates all candidates, model returns `N=score` lines parsed via regex. ~5-15s per rerank for top-20 (one inference instead of 20).
- Live verified end-to-end: PL fuzzy query `napisz mi post na LinkedIn o WCAG` reranks dramatically - top-1 a11y-audit (0.71) vs default top-1 content-writing-lead (0.54) with ffcss-migrate (0.49) close behind.
- Updated `examples/config.yaml.example` to make MLX the recommended default for Mac, ollama as cross-platform alternative.

### Changed
- `make_reranker('mlx')` returns `MLXReranker` instance (was: raised NotImplementedError pointing at ollama).
- `tests/test_reranker.py::test_factory_mlx_returns_real_implementation` (was: `…not_implemented`); platform-aware (skips real load on non-arm64).

## [v0.3.0a0] - 2026-05-09

### Added
- **MLX embedder backend** (Apple Silicon, opt-in via `[mlx]` extras). Default model `mlx-community/Qwen3-Embedding-8B-4bit-DWQ` produces 4096-dim vectors (10× larger than the default sentence-transformers 384-dim). Live verified on M-series: model loads from cache in ~7s, batch of 3 in 0.57s (~190ms/text). Raises RuntimeError on non-arm64 with hint to use sentence-transformers backend.
- **Qdrant store backend** (opt-in via `[qdrant]` extras). Same duck-typed interface as ChromaDB SkillStore. Skill names mapped to deterministic UUID5 from project namespace. Auto-creates collection, recreates on dimension mismatch. Live verified against running localhost:6333 - same instance can serve both skills-radar and sdet-brain via separate collections.
- **Local opt-in usage telemetry** - SQLite event log at `~/.local/share/skills-radar/stats.db`. Three event kinds: search (query, top1 score, top5 names, latency_ms, rewriter_used), load (skill_name, trust, body_len, latency_ms, found), index (count, duration_ms, rebuild). Strict opt-in, no remote telemetry ever.
- **`skills-radar stats` CLI** - rich.Table report with totals, top loaded skills, top queries with miss-rate badge (color-coded green<15% / yellow<30% / red≥30%), recent events with per-kind detail formatting.
- **`skills-radar tui` CLI** - rich.Live based real-time dashboard. 4 panels: trust tier breakdown bars, top queries with miss-rate, top loaded skills, recent events stream with color-coded scores (green≥0.6, yellow≥0.4, red<0.4). Refresh interval configurable via `--refresh`. Demo material for portfolio article.
- **Optional reranker** (cross-encoder over top-k via local LLM). Off by default. `none` (passthrough), `ollama` (local LLM scores 0-10 per pair, robust to errors with ranking fallback), `mlx` (placeholder, raises NotImplementedError pointing to ollama). When enabled, `hybrid_search` pulls a wider candidate pool (default 20) and reranker scores each.
- **9 reranker tests** - NoOp, factory selection, URL validation, mock Ollama scoring → reorder by score, network-error fallback, no-integer-in-response handling, empty candidates. Total: 60 tests pass.

### Changed
- `RetrievalConfig` grew nested `reranker` section (same shape as `rewriter`).
- `StoreConfig` grew `qdrant_url`, `qdrant_collection`, `backend` ('chromadb' | 'qdrant').
- `Config` grew `telemetry` section (enabled, db_path).
- `AppContext` factory `_make_store` selects backend per config and passes embedder dimension so Qdrant collection auto-creates with the right vector size.
- `AppContext.hybrid_search` logs latency + rewriter usage to telemetry; reranks pool when enabled.
- `AppContext.load_record` logs trust tier, body size, found flag.
- `AppContext.reindex` logs duration + rebuild flag.

### Verified
- 60+ skills indexed locally (after dedup), live verified MCP `tools/call` returns expected ranking.
- Telemetry: 4 searches recorded with 115-156ms latency, miss rate 0.0% on default sentence-transformers backend.
- TUI snapshot rendered: 4 panels with trust breakdown bars, recent events color-coded, header shows backend selection.
- ruff check pass, ruff format pass.

## [v0.2.0] - 2026-05-09

### Added
- **14 integration tests** covering reindex, hybrid search (a11y / Vue / content queries), tag filtering, load_record fresh-read, hot-reload upsert/delete, disable-model-invocation honored, mini-index generation, find_skill_files exclusions, and dedup priority across trust tiers. Real embedder + ChromaDB. Coverage 26% → **52%** (app.py 80%, store.py 93%, embedder.py 86%).

### Changed / Fixed
- **Docker healthcheck** now POSTs a real MCP `initialize` handshake instead of GET (which returns 406 by design). Container reports `healthy` in ~1s. Same fix in `docker-compose.yml`.
- ruff/lint pass: `TrustTier` inherits `StrEnum` (UP042); `OllamaRewriter.__init__` validates `http://`/`https://` scheme (S310 belt-and-braces).
- `pyproject.toml`: removed deprecated ANN101/ANN102 ruff ignores (no-ops in current ruff).

### Verified
- Local stdio transport: 60+ skills indexed, hybrid search returns relevant top hits (`wcag accessibility audit` → a11y-orchestrator 0.79).
- Local HTTP transport: init handshake 200 OK, capabilities returned.
- **Docker end-to-end**: `docker compose up` → healthy in 1s → `tools/call search_skills` over HTTP returns identical ranked matches as the local CLI.

## [v0.2.0a0] - 2026-05-09

## [v0.2.0a0] - 2026-05-09

### Added
- **Hot reload** - `watcher.py` with `watchdog` file observer. Created/modified/deleted/moved SKILL.md events trigger debounced (250ms) single-record re-index. Coalesces editor save bursts.
- **Mini-index generator** - `mini_index.py` writes a compact `~/.claude/SKILLS-INDEX.md` (Tier 1 of Two-Tier Discovery). Group by `hub-tags` (default) or `scope`. With 69 skills indexed, output is ~1.9k tokens vs ~6k native (68% reduction).
- **Streamable HTTP transport** - production-grade transport per MCP Python SDK guidance. `stateless_http=True`, `json_response=True` defaults. Pair both for horizontal scaling behind a load balancer.
- **CLI** grew `mini-index` command, `serve --watch` flag, `serve --transport http` flag with `--host`, `--port`, `--path`, `--stateless`, `--json` options.
- **Optional Ollama query rewriter** - opt-in pre-embedding step that rewrites ambiguous queries into richer English keyword phrases via local LLM. Resilient by design: any HTTP/timeout/parse failure falls back to raw query.
- **Docker** - multi-stage Dockerfile pre-bakes embedding model (~90MB) for ~2s container start. Non-root uid 1000, offline HF Hub flags, strict sanitization defaults. `docker-compose.yml` for single-host deployment.
- 3 docs files: `threat-model.md` (4-layer defense in depth), `writing-skills.md` (frontmatter checklist + retrieval signals), `context-engineering.md` (Anthropic principles + Two-Tier Discovery rationale).
- 17 new tests: 7 for `mini_index`, 10 for `rewriter`. All 37 pass.

### Changed
- `TransportConfig` grew `http_host`, `http_path`, `stateless_http`, `json_response` fields.
- `RetrievalConfig` grew nested `rewriter` section.

## [v0.1.0a0] - 2026-05-09

### Added
- Initial alpha. Local-only, stdio MCP transport.
- Two-tool MCP surface: `search_skills(query)` + `load_skill(name)`.
- Hybrid retrieval: BM25 (`rank_bm25`) + dense embeddings (`sentence-transformers/all-MiniLM-L6-v2`), 70/30 fusion by default.
- ChromaDB persistent store, single `skills_v1` collection with cosine HNSW.
- Threat model day-one: trust tiers (TRUSTED / VERIFIED / USER / UNTRUSTED), XML injection stripping, prompt-injection regex catalog, name validation (≤64 chars, lowercase + hyphens, reserved words rejected), size cap (default 64KB).
- Frontmatter parsing: 14 native Claude Code fields + `hub-tags` extension. Backward-compatible (Claude Code ignores unknown frontmatter).
- Same-name dedup across plugin versions: priority `trusted > user > verified > untrusted`, mtime tiebreak.
- CLI: `skills-radar serve | index | list | search | doctor | config-init | version`.
- Sanitized SKILL.md re-read fresh on `load_skill` so live edits surface without restart.
- 20 smoke tests: name validation, sanitize, trust tier, parse_skill_file (minimal/reserved-name/no-frontmatter/size-limit).
- SPEC.md (~2300 words, 15 sections), README.md, architecture deep-dive, onboarding 8-step guide.
- Verified working: 60 skills indexed (after dedup); `wcag accessibility audit` → a11y-orchestrator (0.79); `memory leak in my Vue app` → perf-vue-runtime (0.48).

[Unreleased]: https://github.com/darco81/skills-radar/compare/v0.4.0a0...HEAD
[v0.4.0a0]: https://github.com/darco81/skills-radar/compare/v0.3.0a2...v0.4.0a0
[v0.3.0a2]: https://github.com/darco81/skills-radar/compare/v0.3.0a1...v0.3.0a2
[v0.3.0a1]: https://github.com/darco81/skills-radar/compare/v0.3.0a0...v0.3.0a1
[v0.3.0a0]: https://github.com/darco81/skills-radar/compare/v0.2.0...v0.3.0a0
[v0.2.0]: https://github.com/darco81/skills-radar/compare/v0.2.0a1...v0.2.0
[v0.2.0a0]: https://github.com/darco81/skills-radar/compare/v0.1.0a0...v0.2.0a0
[v0.1.0a0]: https://github.com/darco81/skills-radar/releases/tag/v0.1.0a0
