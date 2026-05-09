# Onboarding - get skill-radar running in 5 minutes

This guide takes you from zero to a working `search_skills` / `load_skill` integration with Claude Code.

## Prerequisites

- macOS, Linux, or Windows (WSL recommended)
- Python 3.11+
- Claude Code CLI installed
- ~150 MB free disk for the embedding model + ChromaDB store

## Step 1 - install

### Option A: from PyPI (when published - F3)

```bash
pip install skill-radar
# or with uv:
uv pip install skill-radar
```

### Option B: from source (current)

```bash
git clone https://github.com/dar-kow/skill-radar
cd skill-radar
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Step 2 - first-run config

Write a default config:

```bash
skill-radar config-init
```

This creates `~/.config/skill-radar/config.yaml` with sensible defaults.

Edit it to add the skill roots you actually want indexed. Defaults already cover:

- `~/.claude/skills` - your personal skills
- `~/.claude/plugins/cache/claude-plugins-official` - installed plugin skills

Add any project-level roots, e.g.:

```yaml
paths:
  - ~/.claude/skills
  - ~/.claude/plugins/cache/claude-plugins-official
  - ~/dev/myproject/.claude/skills
```

## Step 3 - verify environment

```bash
skill-radar doctor
```

You should see:
- ✓ next to each path that exists, with the SKILL.md count
- Embedder backend + model
- Store backend + path

If anything has ✗ next to it, fix the path before continuing.

## Step 4 - index your skills

```bash
skill-radar index
```

First run downloads the embedding model (~90 MB, takes 30-60 s on a normal connection). Subsequent runs are instant.

You'll see something like `✓ Indexed N skills` at the end.

## Step 5 - verify with offline search

```bash
skill-radar search "audit my code for accessibility"
```

You should see top-5 matches with scores. The top hit should be a relevant a11y skill. If your top hit is unrelated, your skill descriptions probably aren't trigger-rich - see `docs/writing-skills.md`.

## Step 6 - wire up Claude Code

Add `skill-radar` to your project's `.mcp.json`:

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

Or globally in `~/.claude/.mcp.json`.

## Step 7 - recover the token budget

Now that `skill-radar` knows your skills, you can stop preloading their full descriptions in every Claude Code session. Edit `~/.claude/settings.json`:

```json
{
  "skillOverrides": {
    "huggingface-skills:huggingface-vision-trainer": "off",
    "huggingface-skills:huggingface-llm-trainer": "off"
  }
}
```

Use `"off"` to drop skills entirely from listing (Claude will discover them via `search_skills`), or `"name-only"` to keep just the name (~80% reduction per skill).

Restart Claude Code. Run `/doctor` - you should see a meaningful drop in skill listing budget.

## Step 8 - try it live

In a Claude Code session, ask something that should match a skill:

> "Help me find what skill to use for memory leaks in Vue."

Claude should call `mcp__skill-radar__search_skills` with a relevant query and surface the top match (probably `perf-vue-runtime`). Then it can call `mcp__skill-radar__load_skill` to fetch the full SKILL.md.

## Troubleshooting

**`skill-radar: command not found`**
The package didn't install or your venv isn't activated. Run `which skill-radar`. If empty, re-install or activate the venv.

**`No SKILL.md files found`**
Your paths don't exist or they're empty. Run `skill-radar doctor` and check the ✓/✗ marks.

**Search returns irrelevant matches**
Either: (a) the relevant skill isn't in your indexed paths, or (b) its description is too vague. Check with `skill-radar list` whether the skill is indexed; if it is, improve its `description` and `when_to_use` fields.

**`DuplicateIDError` during index**
Two SKILL.md files share the same `name:`. skill-radar dedupes by trust tier + mtime, but this error suggests an older version. Update via `pip install -U skill-radar`.

**Claude Code doesn't seem to query skill-radar**
Run `/mcp` in Claude Code to see if the server is connected. If not, check the `.mcp.json` syntax and restart Claude Code.

## Where next

- `docs/architecture.md` - how Two-Tier Discovery works under the hood
- `docs/threat-model.md` - trust tiers and sanitization (when you ingest community skills)
- `docs/writing-skills.md` - how to write skills that index well
- `docs/context-engineering.md` - why this whole approach matters
