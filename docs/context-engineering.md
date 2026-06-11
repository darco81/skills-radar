# Context engineering - why skills-radar exists

> "Find the smallest possible set of high-signal tokens that maximize the likelihood of the desired outcome." - Anthropic, [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

## The problem in one paragraph

Every token in an LLM's context window has a cost - both literal (compute, latency, billing) and qualitative (transformer attention degrades on long inputs). With Claude Code's native skill listing, every installed skill's name + description loads at session start. By the time you have 80+ skills across personal, project, and plugin scopes, you're paying ~6,000 tokens per session **before the user types anything** - and you may use exactly zero of those skills.

This is the inverse of context engineering. The skills you might need are crowding out the context you actually use.

## The Anthropic-blessed pattern

In late 2025, Anthropic shipped two relevant features:

1. **Tool Search Tool** ([docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)) - at the API level. Tools marked `defer_loading: true` are invisible until Claude calls a built-in `tool_search_tool`. Anthropic's evals: 85% token reduction, Opus 4.5 accuracy 79.5% → 88.1% on large tool libraries.

2. **MCP Tool Search for Claude Code** - ships the same idea for MCP-server-provided tools. With 7+ MCP servers, you can blow ~67k tokens before any work begins. Tool Search collapses that.

These solve **MCP tools**. They don't solve **skills**, which are a separate Claude Code mechanism - files in `~/.claude/skills/` that load via the Skill tool, not via MCP.

skills-radar mirrors the exact same pattern (search-then-load, deferred metadata) for skills.

## Two-Tier Discovery - the design

The naive RAG-over-skills idea has a fatal flaw: if Claude doesn't see the skills exist, it never queries the index. Most community "MCP skill server" projects fall into this trap and stay unused.

skills-radar splits discovery into two complementary signals:

### Tier 1 - Mini-index (always preloaded, ~1k tokens)

A flat list of `name + 1-line summary` for every indexed skill, written to `~/.claude/SKILLS-INDEX.md`. Imported into the user's global `CLAUDE.md` so it's visible to Claude every session.

This is the "you know they exist" signal. Without it, Tier 2 is unreachable.

### Tier 2 - On-demand load (via MCP)

Two MCP tools:

- **`search_skills(query)`** - hybrid BM25 + dense retrieval over `description + when_to_use`. Returns top-k matches.
- **`load_skill(name)`** - full sanitized SKILL.md when the agent commits to acting.

Body is fetched only when needed. **No skill instructions live in context until the agent decides to act.**

One constraint to be honest about: `search_skills` indexes `description` + `when_to_use` only - never the body. Retrieval quality is therefore bound to description quality: a skill with a vague one-liner stays hard to find no matter how good its body is. This is the same constraint native Claude Code operates under (it also selects skills from frontmatter descriptions), so a description written for one works for both - see [`writing-skills.md`](./writing-skills.md). The optional query rewriter and reranker exist to compensate on the query side (terse or multilingual queries, close-call rankings); they cannot rescue a description that says nothing.

## The math

For a user with 80 skills:

| Strategy | Per-session cost | Worst case (use 1 skill) |
|---|---|---|
| Native skill listing | ~6,000 tokens | ~6,000 tokens |
| skills-radar Two-Tier | ~1,000 tokens (mini-index) | ~1,000 + ~2,000 = ~3,000 tokens |
| skills-radar - multiple loads (5 skills) | ~1,000 + 5 × 2,000 = ~11,000 tokens | (rare - most sessions load 0-2) |

Net: in the realistic case (1-2 skills loaded per session), skills-radar saves ~3-5k tokens per session. At scale (500 skills), the native approach becomes unworkable; skills-radar's cost stays roughly flat.

## Why this matters beyond token count

Anthropic's [research on transformer attention](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) shows that **long context degrades response quality** - the longer the prompt, the more diluted attention becomes. This is not just a cost story; it's a **quality** story. A leaner prompt gives the model a fighting chance to stay focused.

Compaction, structured note-taking, and just-in-time loading are the three patterns Anthropic identifies for managing long-running context. Two-Tier Discovery is just-in-time loading, applied to a new domain (skills).

## The "discovery dilemma"

Why doesn't a single MCP tool work?

Imagine you ship one MCP tool: `find_relevant_skill(query)`. Claude wakes up at session start, sees this tool, has no clue what skills exist or whether to query. The user asks "help me write a LinkedIn post." Claude either:
- Calls `find_relevant_skill("LinkedIn post writing")` - best case, but only if it occurred to Claude that a skill might help
- Doesn't call anything - answers directly without leveraging the skill ecosystem

Without a Tier 1 surface signal, Tier 2 is invisible. This is why every "MCP skill loader" we found in prior research either:
1. Loads everything anyway (defeating the purpose), or
2. Loads nothing and stays unused

skills-radar's contribution: **the mini-index makes Tier 2 visible without paying full description budget.**

## Threat model is part of context engineering

Honest context engineering accounts for adversarial inputs. Every SKILL.md loaded via `load_skill` becomes part of the agent's context - and skills are arbitrary instructions. Without sanitization + trust tiers, the open-source skill ecosystem is a system-prompt-injection supply chain.

See [`threat-model.md`](./threat-model.md) for our defense-in-depth.

## Further reading

Anthropic / Claude Code official:
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Tool Search Tool docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Claude Code skills docs](https://code.claude.com/docs/en/skills)

Community:
- [MCP Tool Search Pattern (atcyrus.com)](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide)
- [VoltAgent's awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) - 1000+ skills, the corpus we benchmark against

Prior art (MCP skill servers):
- [bobmatnyc/mcp-skillset](https://github.com/bobmatnyc/mcp-skillset) - most mature threat model
- [back1ply/agent-skill-loader](https://github.com/back1ply/agent-skill-loader) - file-watcher patterns
- [gotalab/skillport](https://github.com/gotalab/skillport) - minimal search-then-load reference
