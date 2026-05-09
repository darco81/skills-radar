# `hub-tags` - recommended taxonomy

> Convention for the `hub-tags:` frontmatter field on SKILL.md files. Drives skills-radar's tag-filtered search and mini-index grouping. Backward-compatible with native Claude Code (which ignores unknown frontmatter).

This document is **opinionated, not enforced**. skills-radar accepts any list of strings under `hub-tags:`. The taxonomy below is a recommendation that works at scale (1000+ skill corpora) and aligns with the natural intent categories Claude Code users actually search by.

---

## TL;DR - the canonical 12

```yaml
hub-tags: [a11y, perf, qa, dev, content, ml, ux, devops, docs, infra, sec, ops]
```

| Tag | Domain | Examples from a real corpus |
|---|---|---|
| **a11y** | Accessibility, WCAG, EAA compliance | `a11y-orchestrator`, `a11y-audit`, `a11y-fix`, `wcag-toolkit-lead`, `wcag-static-analyze`, `wcag-dynamic-test` |
| **perf** | Web / app performance audits | `perf-orchestrator`, `perf-vue-runtime`, `perf-bundle-analyzer`, `perf-assets-loading`, `perf-ssr-hydration`, `perf-api-calls` |
| **qa** | Testing, QA workflows, test generation | `qa-test`, `playwright-cli`, Playwright generator/healer/planner agents |
| **dev** | Code-writing skills (refactor, feature work, code review) | `feature-dev:feature-dev`, `code-review:code-review`, `frontend-design:frontend-design`, `simplify` |
| **content** | Brand content, posts, articles, copy | `content-writing-lead`, From the Field draft skills, sprint recap skills |
| **ml** | ML / AI workflow skills | `huggingface-best`, `train-sentence-transformers`, `huggingface-llm-trainer`, `huggingface-vision-trainer`, `transformers-js` |
| **ux** | Design system, Figma, design council | `ds-orchestrator`, `ds-extract`, `ds-map`, `ds-diff`, `ds-generate`, `frontend-design`, `design-council` |
| **devops** | CI/CD, releases, branch flow, PR management | `commit-commands:commit-push-pr`, `superpowers:finishing-a-development-branch`, `commit-commands:clean_gone` |
| **docs** | Documentation, technical writing, READMEs | `init` (CLAUDE.md), README skills, changelog skills |
| **infra** | Docker, networking, deployment, VPS | `bodzio-compose-view`, deploy automation skills |
| **sec** | Security review, threat modeling, compliance | `security-review`, security-guidance plugin skills |
| **ops** | Operations: Slack, Linear, Jira, status updates, standups | `linear-workflow`, `linear-status`, `linear-new-task`, `slack:standup`, `slack:summarize-channel` |

---

## How to apply tags

### 1. Lead with the **primary** domain, then add scopes

A skill that audits Vue 3 performance is `perf` first, then `vue` if you want a finer scope:

```yaml
name: perf-vue-runtime
hub-tags: [perf, vue]
```

A WCAG-specific accessibility audit:

```yaml
name: wcag-toolkit-lead
hub-tags: [a11y, wcag]
```

### 2. Multi-tag for cross-cutting skills

A11y + content (writing accessible copy):

```yaml
hub-tags: [a11y, content]
```

DevOps + Linear (release announcement workflows):

```yaml
hub-tags: [devops, ops]
```

Skill-radar's filtered search returns matches if **any** tag intersects:

```python
# Searches with tag filter ['a11y'] match either pure a11y OR a11y+content skills
search_skills(query="audit", tags=["a11y"])
```

### 3. **Don't** use tags as natural-language descriptors

Bad:

```yaml
hub-tags: [accessibility, performance, "test automation", quality-assurance]
```

Good:

```yaml
hub-tags: [a11y, perf, qa]
```

Reason: short tags compose better in URLs, mini-index headers, CLI filters. Long natural-language tags are hard to remember and inconsistent across skill authors.

### 4. Avoid ambiguous tags

**`api`** - does this mean "skill audits API patterns" or "skill calls APIs"? Use `perf-api`, `dev-api`, `ops-api` etc. as needed, not bare `api`.

**`vue`/`react`/`svelte`** - these are framework scopes, fine to use as **secondary** tags but never primary. Primary is what the skill *does* (perf / a11y / dev), not what stack it targets.

**`general`/`misc`/`other`** - never. If you can't classify, leave `hub-tags` empty.

---

## Bilingual / Polish corpora hint

If your skill corpus is bilingual (e.g. some skills are PL-only Crehler internal, others EN), put **English tags** in `hub-tags`. Search trigger phrases inside `description` / `when_to_use` can be bilingual; tags are the cross-cutting scope axis and stay in one language.

```yaml
name: ffcss-migrate
description: |
  Migracja komponentów Vue z Tailwind CSS na Forge Front CSS System (FFCSS).
  Triggers (PL): "migruj do FFCSS", "tailwind to ffcss", "migrate component"
hub-tags: [dev, vue, css]   # English tags, PL+EN triggers
```

---

## Anti-patterns

| Anti-pattern | Why it's bad | What to do instead |
|---|---|---|
| Single tag `[skill]` | Adds zero info, every skill is a "skill" | Drop it; use `hub-tags: []` if no domain fits |
| Tag = skill name | `hub-tags: [perf-vue-runtime]` is redundant | Use the domain tag |
| Tags differ between similar skills | `perf-vue-runtime` has `[perf, vue]` but `perf-bundle-analyzer` has `[performance, javascript]` | Pick one taxonomy and apply consistently |
| Capitalized tags | `hub-tags: [A11y, WCAG]` | Lowercase everything; ranking is case-insensitive but consistency helps mini-index |
| Stack tag without domain | `hub-tags: [vue]` only | Add primary domain: `[perf, vue]` or `[a11y, vue]` |

---

## How skills-radar uses tags

**Filtered search** - `search_skills(query="...", tags=["a11y"])` returns only skills whose `hub-tags` intersect with the requested set. Use case: "find me an a11y skill for component audit" instead of pulling unrelated `wcag-toolkit-lead` clone hits.

**Mini-index grouping** - `skills-radar mini-index --group-by hub_tags` produces sections like:

```markdown
## a11y
- **a11y-orchestrator** - Full WCAG 2.1 AA audit, dispatches 7 specialized agents
- **a11y-audit** - Crehler Enterprise WCAG 2.1 AA accessibility audit for Vue 3/Nuxt
- **wcag-toolkit-lead** - sdet-wcag-toolkit orchestrator routes audit/fix/report

## perf
- **perf-orchestrator** - Full Nuxt 3 / Vue 3 performance audit, 5 agents
...
```

A skill with multiple `hub-tags` appears under each section. Skills with empty `hub-tags` fall to the **uncategorized** section - that's the signal to add tags.

---

## Future evolution

This taxonomy is v1. We expect it to evolve with:

- **New domains** - when a critical mass of skills doesn't fit the canonical 12 (e.g., `data` for data engineering / ETL workflows, `legal` for compliance, etc.)
- **Sub-namespaces** - if a single tag accumulates >50 skills, consider splitting (e.g., `a11y` → `a11y-audit` + `a11y-fix` + `a11y-test`)
- **Community contributions** - if you publish skills under `awesome-claude-skills` or similar, propose tag additions via PR with example skills

For now, **stick to the 12**. Compose them with stack-scope tags (`vue`, `react`, `python`, `rust`) as needed. Don't invent new top-level domains until pressure forces it.

---

## Migration path for existing skill corpora

If your current skills don't have `hub-tags`:

1. Bulk audit - `skills-radar list` shows all indexed skills with current metadata
2. Group by intent - for each skill, pick 1-3 tags from the canonical 12
3. Edit SKILL.md frontmatter, add `hub-tags: [...]`
4. With watcher on, reindex is automatic; otherwise `skills-radar index --rebuild`
5. Verify: `skills-radar list --tag a11y` etc. should return expected sets

For a 60-skill corpus, this is ~30-45 minutes of careful work. Worth it because **filtered search precision improves dramatically** - the difference between "first try, exact hit" and "fuzzy ranking with false positives close behind".
