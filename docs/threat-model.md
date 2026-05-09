# Threat Model

> Every SKILL.md is treated as adversarial input. This document explains why and how.

## Why this matters

A SKILL.md file is loaded directly into a host agent's context window as instructions. From the model's perspective, the difference between a system prompt and a skill body is mostly nominal - both shape behavior. **A malicious skill is a system-prompt injection vector.**

Common attack surfaces:

1. **Open-source skill collections** (e.g., the 1000+ in `awesome-agent-skills`) - anyone can submit. Quality control varies.
2. **Plugin marketplaces** - even legitimate plugins update over time; a hijacked maintainer account can ship a malicious skill.
3. **Project-cloned skills** - clone a repo, suddenly its `.claude/skills/` are part of your scan paths.
4. **User-authored mistakes** - your own future skill might paste something you didn't sanity-check.

Naive RAG over skills loads any of these as authoritative instructions. We refuse to do that.

## Defense in depth

skills-radar ships four layers of defense, applied at ingest:

### Layer 1 - Trust tier assignment

Every skill is tagged at ingest with one of:

| Tier | Source | Default treatment |
|---|---|---|
| **TRUSTED** | `~/.claude/skills`, project `.claude/skills`, paths in `trust.trusted_paths` config | Pass-through after light sanitization |
| **VERIFIED** | `~/.claude/plugins/cache/claude-plugins-official/**` | Light sanitization, log warnings |
| **USER** | Other paths under `~/.claude/skills/` (subdirectories owned by user) | Trusted-local - light sanitization |
| **UNTRUSTED** | Anything else (third-party paths added without explicit trust) | Strict sanitization, blocked patterns rejected |

The trust value is exposed in `load_skill` responses. Downstream agents (or human-in-the-loop wrappers) can refuse to execute UNTRUSTED skills.

### Layer 2 - Frontmatter validation

On every ingest:

- `name` must be ≤64 chars, lowercase + digits + hyphens, leading/trailing alphanumeric
- `name` cannot be a reserved word (`anthropic`, `claude` - case-insensitive)
- Frontmatter must be valid YAML, must be a dict, must contain `name`
- Indexed text (`description + when_to_use`) must be non-empty

Skills failing any of these are dropped with a warning (not an error - we keep the rest of the index healthy).

### Layer 3 - Body sanitization

Body content is run through:

#### XML-like injection tag removal

Patterns of the form `<system>...</system>`, `<override>...</override>`, `<jailbreak>...</jailbreak>`, `<admin>...</admin>`, `<sudo>...</sudo>`, `<root>...</root>` are stripped and replaced with `[REDACTED-INJECTION]`. Logged as a warning.

#### Prompt-injection regex catalog

Default catalog (extensible via config):

```
ignore (?:all\s+)?(?:previous|prior) instructions
disregard (?:your\s+)?system prompt
you are (?:now|actually) (?:a\s+)?[a-z]+
forget everything (?:above|before)
<\|im_(?:start|end)\|>
```

These patterns are **detected, not rewritten** - the body passes through with a warning attached. The agent receives the warning in `load_skill` response.

Why detect rather than rewrite: rewriting risks breaking legitimate references (e.g., a skill that itself documents prompt injection). The agent decides whether to act.

#### Live-execution syntax

Claude Code interprets `` !`command` `` syntax in SKILL.md by executing the command and inlining the output **before Claude sees the content**. For non-Claude-Code clients (Cursor, Claude Desktop, custom agents), the syntax is dead - they'd see literal backticks.

skills-radar's default behavior: pass through (preserves Claude Code semantics). With `sanitization.strip_live_exec: true`, the syntax is replaced with `[LIVE-EXEC-STRIPPED]` and the body is reflagged.

### Layer 4 - Size cap

UTF-8 byte length per SKILL.md is capped at 64KB by default (`sanitization.max_skill_size_kb`). A skill exceeding the cap is rejected entirely - large bodies often indicate either a bug (wrong file ingested) or an attempted DoS (massive payload).

## What we do NOT do

- **No execution** - skills-radar never runs commands, never imports skill code, never resolves file references inside SKILL.md. We only index and serve.
- **No automatic policy** - we surface trust tier and warnings; the agent decides whether to honor them.
- **No cryptographic signing yet** - VERIFIED tier is path-based, not signature-based. Crypto signing is on the F4 backlog (see SPEC §8).

## Recommendations for downstream agents

If you're building an agent on top of skills-radar:

1. **Refuse UNTRUSTED skills by default.** Make the user explicitly opt-in per skill.
2. **Show warnings to the human.** If `warnings` array is non-empty in `load_skill` response, surface it before acting.
3. **Cap how many skills are loaded per turn.** Once loaded, a skill is in context for the rest of the session. Loading 10 untrusted-by-default skills "just to see" is the threat scenario.
4. **Don't auto-execute on `disable-model-invocation: true` skills.** Even if the user names them, treat as user-only.
5. **Check `disable_model_invocation` field** before relying on a search hit.

## Future hardening (F4 backlog)

- Cryptographic signing for VERIFIED tier (skills signed by trusted keys)
- LLM-based prompt-injection scanning (e.g., a small local model classifies suspicious bodies)
- Anomaly detection on skill body diffs (sudden 10x size growth or new injection patterns flagged)
- Sandbox `bundled_files` referenced from SKILL.md (today they're just enumerated)
- Audit log of all ingest events with hashes (for forensics if a malicious skill slips through)

## Reporting a security issue

If you find a vulnerability in skills-radar (e.g., a sanitization bypass), please email `d.kowalski@sdet.it` rather than opening a public issue. We aim to acknowledge within 48h.
