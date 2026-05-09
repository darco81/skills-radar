"""Sanitization + trust tier assignment.

Every SKILL.md is treated as adversarial input. See SPEC §5.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

RESERVED_NAMES = frozenset({"anthropic", "claude"})

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")

XML_INJECTION_PATTERN = re.compile(
    r"<(?:system|override|jailbreak|admin|sudo|root)[^>]*>.*?</(?:system|override|jailbreak|admin|sudo|root)>",
    re.IGNORECASE | re.DOTALL,
)

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(?:your\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+(?:now|actually)\s+(?:a\s+)?[a-z]+", re.IGNORECASE),
    re.compile(r"forget\s+everything\s+(?:above|before)", re.IGNORECASE),
    re.compile(r"<\|im_(?:start|end)\|>", re.IGNORECASE),
)

LIVE_EXEC_PATTERN = re.compile(r"!`[^`]+`")


class TrustTier(str, Enum):
    """Trust tiers - see SPEC §5."""

    TRUSTED = "trusted"
    VERIFIED = "verified"
    USER = "user"
    UNTRUSTED = "untrusted"


def validate_name(name: str | None) -> bool:
    """Validate skill name per Claude Code spec.

    Rules: ≤64 chars, lowercase + hyphens + digits, not reserved.
    """
    if not name or len(name) > 64:
        return False
    if name.lower() in RESERVED_NAMES:
        return False
    return bool(NAME_PATTERN.match(name))


def sanitize_body(body: str, *, strip_live_exec: bool = False) -> tuple[str, list[str]]:
    """Sanitize SKILL.md body.

    Returns (sanitized_body, warnings). Warnings are flags, not errors -
    caller decides whether to surface them.
    """
    warnings: list[str] = []

    if XML_INJECTION_PATTERN.search(body):
        warnings.append("xml_injection_tags_detected")
        body = XML_INJECTION_PATTERN.sub("[REDACTED-INJECTION]", body)

    for pat in INJECTION_PATTERNS:
        if pat.search(body):
            warnings.append(f"injection_pattern_detected:{pat.pattern[:40]}")

    if strip_live_exec and LIVE_EXEC_PATTERN.search(body):
        warnings.append("live_exec_syntax_stripped")
        body = LIVE_EXEC_PATTERN.sub("[LIVE-EXEC-STRIPPED]", body)

    return body, warnings


def determine_trust_tier(skill_path: Path, trusted_paths: list[Path]) -> TrustTier:
    """Decide trust tier from filesystem location.

    Logic (top to bottom, first match wins):
      1. Explicit trusted_paths (config) → TRUSTED
      2. ~/.claude/plugins/cache/claude-plugins-official/** → VERIFIED
      3. ~/.claude/skills/** or any */.claude/skills/** → USER
      4. Anything else → UNTRUSTED
    """
    skill_path = skill_path.expanduser().resolve()

    for tp in trusted_paths:
        try:
            tp_resolved = tp.expanduser().resolve()
            if skill_path.is_relative_to(tp_resolved):
                return TrustTier.TRUSTED
        except (ValueError, OSError):
            continue

    plugin_root = (Path.home() / ".claude" / "plugins" / "cache" / "claude-plugins-official").resolve()
    try:
        if skill_path.is_relative_to(plugin_root):
            return TrustTier.VERIFIED
    except (ValueError, OSError):
        pass

    user_root = (Path.home() / ".claude" / "skills").resolve()
    try:
        if skill_path.is_relative_to(user_root):
            return TrustTier.USER
    except (ValueError, OSError):
        pass

    if ".claude/skills" in skill_path.as_posix() or ".claude\\skills" in str(skill_path):
        return TrustTier.USER

    return TrustTier.UNTRUSTED


def is_size_ok(body: str, max_kb: int) -> bool:
    """Check skill body is under max_kb (UTF-8 byte length)."""
    return len(body.encode("utf-8")) <= max_kb * 1024
