# From the Field - bonus episode (EN)

**Working title:** "My Claude Code prompt was bleeding 6,000 tokens before I typed a word."

**Format:** LinkedIn post (long-form), bilingual rule applies - PL version posted as first comment.

**Status:** draft v1 - needs voice pass before publish.

---

## Hook

I ran `/doctor` in Claude Code yesterday. Before I typed a single character, my prompt was 6,000 tokens deep.

That's not the model thinking. That's not my project context. That's just **skill descriptions** - every installed skill across personal, project, and plugin scopes, preloaded into the system prompt at session start.

I have ~80 skills. Not because I'm a hoarder - because Claude Code's plugin marketplace makes it easy, and a sprawling skill library is genuinely useful. The cost is invisible until you measure it.

## The thing nobody fixed

Late last year, Anthropic shipped **Tool Search Tool** - tools marked `defer_loading: true` are invisible until Claude calls a built-in `tool_search_tool`. Their internal numbers: 85% token reduction, Opus 4.5 accuracy 79.5% → 88.1% on large tool libraries. They shipped the same thing for MCP servers in Claude Code shortly after.

But Tool Search is for **tools**. Skills are a different mechanism - files in `~/.claude/skills/`, loaded via the Skill tool, not via MCP. Anthropic hasn't shipped the equivalent yet. Issues #16160 and #19105 sit open.

So I built it. Not because nobody else has tried - there are several `mcp-skill-server` projects in the wild - but because **none of them solve the discovery dilemma**.

## The discovery dilemma

Naive RAG over skills fails at the first hurdle:

> If the agent doesn't see the skills exist, it never queries the index. If it never queries the index, the lazy loading is pointless.

Most community projects ship a single MCP tool, "find_relevant_skill," and assume Claude will query it on every turn. It doesn't. Without a Tier-1 surface signal, Tier-2 retrieval is invisible.

## Two-Tier Discovery

`skills-radar` splits discovery in two:

**Tier 1 - Mini-index in CLAUDE.md, ~1k tokens.** A flat `name + 1-line summary` per skill, grouped by category. Always visible. Cheap. Tells Claude *what exists.*

**Tier 2 - On-demand load via MCP.** Two tools: `search_skills(query)` for fuzzy intent, `load_skill(name)` when the name is obvious. Full SKILL.md body fetched only when the agent commits to acting.

Result on my own machine: **6,000 tokens → 1,900 tokens for the same 80 skills.** ~68% reduction. Doesn't matter if I scale to 500 skills tomorrow - the cost stays roughly flat.

## Built like Anthropic would

Stack matches Anthropic's published guidance:
- MCP Python SDK with **Streamable HTTP** transport (`stateless_http=True, json_response=True`)
- Hybrid retrieval: BM25 + dense embeddings, 70/30 weighted
- Index over `description + when_to_use`, never the body - body bloat destroys similarity scoring
- Threat model day-one: trust tiers, prompt-injection scanning, XML strip, size cap, name validation. SKILL.md is system-prompt-injection input. Treat it that way.
- Two tools, not seven. Eat your own dogfood - every tool description is a token cost in the consuming agent's context.

## What you get

- `pip install skills-radar` (when published)
- `skills-radar serve --transport stdio` for local Claude Code; `--transport http` for Docker / production
- Hot reload - drop a SKILL.md, indexed in <1s
- Optional local-LLM query rewriter (Ollama) - rewrites ambiguous queries into richer keyword phrases, off by default
- Air-gapped friendly - pre-baked Docker image, offline HF Hub flags
- Multi-client - Claude Code, Cursor, Claude Desktop, custom MCP agents

Repo: **github.com/dar-kow/skills-radar** (link in first comment for the algorithm gods)

## Call to action

Drop your skill count in the comments. I'll guess your token bleed.

If you've solved this differently, I want to see it - there's no monopoly on a good idea, and the prior art (`bobmatnyc/mcp-skillset`, `back1ply/agent-skill-loader`, `gotalab/skillport`) all got pieces right that I learned from.

---

## Notes for self before publishing

- Open with the actual `/doctor` screenshot - show the bleed, don't just describe it
- Demo GIF: 30-second terminal capture of `search_skills` → `load_skill` flow
- Cross-link the next From the Field episode topic in last paragraph
- PL link as first comment (per memory rule)
- Tag: nobody - algorithmic reach, not name-drop economy
- Posting time: Wednesday morning CET (best engagement on technical posts)
- 2nd comment within 30min: "if you want the full architecture write-up, SPEC.md in the repo is ~2300 words, no fluff"
