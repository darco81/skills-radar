# Convention: `metadata.radar.requires_tools`

**Status:** adopted 2026-06-11 — first real-world use of the conditional-activation
fields shipped in v0.5.0a0 (PR #1). 24 resources annotated across two repos
(`~/.claude/skills` commit `cc839b6`, 13 skills + five-minds via symlink in
umysl-pieciu `9475f11`; `~/.claude/agents` commit `5f4a357`, 10 agents).

## The field

```yaml
---
name: my-skill
description: ...
metadata:
  radar:
    requires_tools: [jarvis, gh]
---
```

`metadata.radar.*` is the agentskills.io-style namespace (same pattern as
Hermes' `metadata.hermes.*`). The indexer also accepts top-level
`requires_tools` as a fallback (`indexer.py: _radar_meta` + `_list_field`).

Radar **exposes, never filters** — `search_skills` returns the list verbatim
and the consuming agent (Hermes routing, CC session) applies environment
policy. Same contract as the `trust` field.

## Naming convention (set by this adoption)

- Flat, lowercase, hyphenated identifiers.
- **CLI binaries** by binary name: `node`, `gh`, `pnpm`, `uv`, `k6`,
  `playwright-cli`, `python3`.
- **Local services/stacks** by stack name: `jarvis` (n8n + analytics-api +
  action queue), `sdet-brain` (Qdrant RAG stack + $BRAIN_HOME), `ollama`.
- **MCP servers** by server name with `-mcp` suffix when the bare name would
  be ambiguous: `figma-mcp`; bare when self-describing: `claude-in-chrome`.
- **Browser runtime via Playwright plugin MCP**: `playwright` (distinct from
  `playwright-cli`, the standalone CLI wrapper).

## What counts as a requirement

- **HARD runtime deps only** — the resource cannot perform its core job
  without it. A missing hard dep means "don't route here".
- **Optional deps are omitted** — e.g. `flaky-analytics` lists `[node]` but
  NOT `gh`: fetching from GHA is optional, the core analyzes local report
  dirs without it. Listing `gh` would wrongly gate the whole skill.
- **Universal tools are omitted** — `git`, `curl`, `bash`, `rsync` exist on
  every dev machine; listing them is noise.
- **Knowledge/analysis-only resources carry no block at all** — an empty
  `requires_tools: []` is never written; absence == no requirements.
- **Domain mentions are not deps** — `test-creator` WRITES Playwright code
  but has no Bash tool, so it cannot run anything: `playwright` is its
  domain, not its dependency. Same logic applies to docs-only skills that
  merely mention Lighthouse or Docker.

## Adopted annotations (2026-06-11)

| Resource | requires_tools |
|---|---|
| skills: qa-test, bodzio-compose-view, bodzio-figma-style | jarvis |
| skill: bodzio-view-pipeline | jarvis, gh |
| skills: brain-extract, content-writing-lead, sdet-brain-usage | sdet-brain |
| skill: ds-extract | figma-mcp |
| skill: ds-preview | pnpm |
| skill: generate-mvp | figma-mcp, pnpm |
| skill: five-minds | uv, ollama |
| skill: flaky-analytics | node |
| skill: playwright-cli | playwright-cli |
| skill: ui-ux-pro-max | python3 |
| agents: playwright-test-{generator,healer,planner} | playwright-cli |
| agent: qa-browser-tester | playwright-cli, claude-in-chrome |
| agent: qa-figma-comparator | playwright-cli, figma-mcp, claude-in-chrome |
| agent: qa-reporter | jarvis |
| agents: visual-test-{generator,healer,planner} | playwright |
| agent: design-fidelity-gate | figma-mcp, playwright |

Everything else in `~/.claude/skills` (24) and `~/.claude/agents` (10) is
knowledge/analysis-only and deliberately unannotated.

## Future work

- Consumer side: teach Hermes routing / CC session policy to downrank
  resources whose `requires_tools` are absent from the live environment
  (radar stays a pure metadata carrier).
- `platforms` and `fallback_for_tools` remain unused — adopt with the same
  "hard requirements only" discipline when a real case appears.
