# Contributing to skill-radar

Thanks for considering a contribution. This project's goal is to be a small, sharp, well-tested tool - not a kitchen sink.

## Quick start

```bash
git clone https://github.com/dar-kow/skill-radar
cd skill-radar
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -q
```

If `pytest` reports any failures, file an issue before opening a PR - that's a `main` branch regression, not your problem.

## Scope

We accept PRs for:

- **Bug fixes** - anything breaking the search/load happy path
- **Test coverage** - `app.py`, `watcher.py`, `store.py`, `embedder.py` are still under-tested
- **Docs** - corrections, new examples, translations
- **Pluggable backends** - new embedder backends (Voyage, OpenAI, MLX flavor variants) following the `EmbedderProtocol` interface
- **Pluggable stores** - new vector stores (Qdrant client adapter) following the `SkillStore` interface
- **Threat model improvements** - new injection patterns, validation rules

We're **cautious** about:

- New MCP tools - adding tools beyond `search_skills`/`load_skill` increases surface area for every connected agent. Strong case needed.
- New CLI commands - keep the surface small and orthogonal.
- Heavy dependencies - current footprint (~150MB with model) is a feature, not a bug.

We will **decline**:

- Skill execution / running shell commands from skill bodies - out of scope by design (see [`docs/threat-model.md`](./docs/threat-model.md))
- Skill authoring tools - use [skill-creator](https://github.com/anthropics/claude-code) instead
- Multi-tenant auth / RBAC - local-first tool

## Standards

### Code

- Python 3.11+
- `ruff` for lint + format (`ruff check . && ruff format .`)
- `mypy` strict mode (`mypy src/`)
- Prefer type hints + small functions over comments
- No `print()` in source code that runs under stdio transport - stderr only (otherwise you corrupt the JSON-RPC stream)

### Tests

- All new behavior must have a test
- Tests must not require network (use `unittest.mock.patch` to stub out HTTP)
- Tests must not require a running Ollama / external service
- `pytest -q` should pass in <2s for the unit-test suite

### Commits

- Conventional Commits style (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`)
- Subject ≤72 chars, imperative mood
- Body explains *why*, not *what* (the diff shows what)
- One logical change per commit

### PRs

- Link to an issue when applicable
- Update CHANGELOG.md under `[Unreleased]`
- Keep PR scope tight - one feature or fix per PR
- We squash-merge PRs by default

## Local LLM use

If you're contributing a feature that touches the optional Ollama / MLX / Voyage backends, please test against at least the **default** path (sentence-transformers, no rewriter) to ensure nothing breaks for users without those extras installed.

## Reporting security issues

For vulnerabilities (sanitization bypasses, injection patterns we miss, etc.), email **d.kowalski@sdet.it** rather than opening a public issue. We aim to acknowledge within 48h.

## Licensing

By contributing, you agree your changes are licensed under the project's MIT license.
