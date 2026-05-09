# Writing skills that index well

> A skill that's never discovered is a skill that doesn't exist. Here's how to write SKILL.md files that surface when they should.

This guide is for anyone authoring skills - your own personal collection, a project's `.claude/skills/`, or a public skill plugin.

## The two retrieval signals

skill-radar indexes a single combined string per skill: `description + "\n\n" + when_to_use`. **It does not index the body.** Everything below the frontmatter is invisible to retrieval until the skill is loaded.

What this means: every keyword you want to be findable on must appear in `description` or `when_to_use`. Save the deep details (routing matrices, code examples, multi-step workflows) for the body - they'll load when the skill activates, but they don't help discovery.

## Frontmatter checklist

Minimum viable:

```yaml
---
name: my-skill-name
description: Short, action-first sentence describing what this does and for whom.
when_to_use: |
  Triggers: "user phrase 1", "user phrase 2", "/my-skill".
  Use when: situational signal A, signal B.
  Don't use: anti-pattern A, anti-pattern B.
hub-tags:
  - perf
  - vue
---
```

### `name`

- Lowercase, hyphens, digits only
- ≤64 chars
- Cannot be `anthropic` or `claude` (case-insensitive - both reserved)
- Cannot start or end with a hyphen
- Make it searchable on its own: `wcag-toolkit-lead` > `lead`

### `description`

- Lead with **what it does**, then **for whom / on what**
- One sentence, ≤200 chars (gets clipped at 1024 in Claude Code's listing)
- Include 2-3 keywords a user would naturally type when needing this skill
- Avoid filler ("This skill helps you do X" → just "Do X")

❌ **Bad:** "This is a skill that handles things related to performance."
✅ **Good:** "Audit Vue 3 runtime performance - re-renders, watcher leaks, missing shallowRef/v-once, large reactive objects, slow INP."

### `when_to_use`

This is where you bake in **trigger phrases** the user might say. Three sub-fields conventional:

- **Triggers:** literal phrases. The closer to natural speech, the better.
- **Use when:** situational conditions.
- **Don't use:** anti-patterns. Helps disambiguate from sibling skills.

❌ **Bad:** "Use when needed."
✅ **Good:**
```yaml
when_to_use: |
  Triggers: "audit Vue performance", "INP issues", "Vue rerendering",
  "watcher leak", "shallowRef", "v-once", "reactive object too large".
  Use when: pre-release perf gate, user reports janky scrolling,
  Lighthouse INP regression.
  Don't use: bundle size (use perf-bundle-analyzer), hydration
  (use perf-ssr-hydration), or non-Vue frameworks.
```

### `hub-tags` (skill-radar extension)

A list of category tags for filtered search and mini-index grouping. Backward-compatible - Claude Code ignores unknown frontmatter.

Recommended taxonomy (working draft):
- **a11y, perf, qa, ds, dev, ml, content, devops, infra, sec, ux, write**

Multiple tags are encouraged when relevant. `hub-tags: [perf, vue]` lets a user filter by either.

## Body - what goes in vs what stays out

### Goes in body (loaded on `load_skill`):
- Full routing matrix
- Code examples
- Decision rules / hard rules
- Step-by-step workflows
- "Out of scope" notes
- References to bundled files

### Stays out of body (or duplicated in description/when_to_use):
- Trigger phrases - those go in `when_to_use`
- Description summary - that goes in `description`

## Trigger-rich vs trigger-lean - the test

If you wrote a skill called `perf-vue-runtime`, the hybrid retriever should surface it for queries like:
- "my Vue app is slow"
- "memory leak in Vue"
- "fix re-renders"
- "watcher cleanup"
- "INP regression"

Test it:

```bash
skill-radar search "my Vue app is slow"
```

If your skill is in the top 3 with a score ≥0.4, you're good. If not, iterate on `description` and `when_to_use`.

## Multi-language hint

If your user base writes queries in multiple languages (e.g., Polish + English), put trigger phrases in **both** in `when_to_use`. Hybrid retrieval handles language differences via embedding similarity, but lexical (BM25) only matches exact tokens. Bilingual triggers make matches more robust.

```yaml
when_to_use: |
  Triggers (EN): "WCAG audit", "accessibility check".
  Triggers (PL): "audyt dostępności", "sprawdź WCAG".
```

## Common pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Vague description | "this skill helps with stuff" | Lead with the verb + object |
| Empty `when_to_use` | Low recall on natural queries | Add 5-10 trigger phrases |
| Body keywords without description echo | Skill loaded by name only, never by query | Move 1-2 keywords to description |
| Reserved name | Skill silently dropped on ingest | Rename - never use `claude` / `anthropic` |
| Same name as another skill | One overrides the other (trust tier wins) | Make name unique within scope |
| `description` >1024 chars | Truncated in Claude Code listing | Move detail to body, keep summary tight |

## Iteration workflow

1. Write the skill.
2. Re-index: `skill-radar index` (or rely on hot-reload if `serve --watch`).
3. Run 5-10 queries you expect to hit it: `skill-radar search "..."`.
4. If miss: rewrite `description` and `when_to_use`.
5. Repeat until 80%+ of expected queries land your skill in top 3.

## Skills that orchestrate (lead/orchestrator pattern)

If your skill **dispatches** to other skills (e.g., `wcag-toolkit-lead` routes to `wcag-audit`, `wcag-fix`, etc.), make that visible:

- Description should say "orchestrator" or "lead" or "router"
- `when_to_use` should list domain triggers
- Body contains the routing matrix
- Sub-skills are independently indexed - they show up too
- Use `hub-tags` to colocate them: lead and sub-skills share a tag

Example: `wcag-toolkit-lead` and its 5 sub-skills (`wcag-audit`, `wcag-fix`, `wcag-static-analyze`, `wcag-dynamic-test`, `wcag-report`) all carry `hub-tags: [a11y, wcag]`.

## See also

- `docs/architecture.md` - how Two-Tier Discovery works under the hood
- `docs/threat-model.md` - what gets sanitized at ingest
- `docs/onboarding.md` - getting set up the first time
