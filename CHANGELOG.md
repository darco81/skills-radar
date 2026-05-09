# Changelog

All notable changes to skills-radar are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned for v0.3.0 (first public)
- PyPI publish via GitHub Actions release workflow
- From the Field bonus episode (EN + PL) goes live
- README install GIF / demo screencast

### Planned for v0.4.0 / post-1.0
- MLX `Qwen3-Embedding-8B` backend for Apple Silicon (opt-in)
- Local opt-in usage telemetry, TUI dashboard
- Voyage / OpenAI embedder backends
- Auto-discovery from GitHub repos (e.g., `awesome-agent-skills`)

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

[Unreleased]: https://github.com/dar-kow/skills-radar/compare/v0.2.0...HEAD
[v0.2.0]: https://github.com/dar-kow/skills-radar/compare/v0.2.0a1...v0.2.0
[v0.2.0a0]: https://github.com/dar-kow/skills-radar/compare/v0.1.0a0...v0.2.0a0
[v0.1.0a0]: https://github.com/dar-kow/skills-radar/releases/tag/v0.1.0a0
