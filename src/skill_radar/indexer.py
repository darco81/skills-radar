"""SKILL.md scanner + parser.

Parses YAML frontmatter, extracts indexed text (description + when_to_use),
sanitizes body, assigns trust tier.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from skill_radar.sanitize import (
    TrustTier,
    determine_trust_tier,
    is_size_ok,
    sanitize_body,
    validate_name,
)

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


@dataclass
class SkillRecord:
    """Parsed + sanitized skill record. The full domain object."""

    name: str
    description: str
    when_to_use: str
    indexed_text: str
    body: str
    body_sanitized: str
    warnings: list[str]
    frontmatter: dict
    hub_tags: list[str]
    trust: TrustTier
    path: str
    scope: str
    disable_model_invocation: bool = False
    bundled_files: list[str] = field(default_factory=list)


def parse_skill_file(
    path: Path,
    *,
    trusted_paths: list[Path],
    max_size_kb: int = 64,
    strip_live_exec: bool = False,
) -> SkillRecord | None:
    """Parse one SKILL.md file. Returns None if invalid (logged)."""
    path = path.expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None

    if not is_size_ok(text, max_size_kb):
        logger.warning("Skill exceeds max size (%d KB): %s", max_size_kb, path)
        return None

    match = FRONTMATTER_RE.match(text)
    if not match:
        logger.debug("No YAML frontmatter in %s", path)
        return None

    fm_yaml, body = match.group(1), match.group(2)

    try:
        fm_data = yaml.safe_load(fm_yaml) or {}
    except yaml.YAMLError as exc:
        logger.warning("YAML parse error in %s: %s", path, exc)
        return None

    if not isinstance(fm_data, dict):
        logger.warning("Frontmatter is not a dict in %s", path)
        return None

    name = fm_data.get("name")
    if not validate_name(name):
        logger.warning("Invalid or reserved name %r in %s", name, path)
        return None

    description = (fm_data.get("description") or "").strip()
    when_to_use = (fm_data.get("when_to_use") or "").strip()
    hub_tags = fm_data.get("hub-tags") or fm_data.get("hub_tags") or []
    if not isinstance(hub_tags, list):
        hub_tags = []
    disable_invoke = bool(fm_data.get("disable-model-invocation", False))

    indexed_text = description
    if when_to_use:
        indexed_text = f"{indexed_text}\n\n{when_to_use}".strip()

    if not indexed_text:
        logger.warning("Empty description+when_to_use in %s", path)
        return None

    body_sanitized, warnings = sanitize_body(body, strip_live_exec=strip_live_exec)

    trust = determine_trust_tier(path, trusted_paths)
    scope = _scope_from_path(path)
    bundled_files = _collect_bundled_files(path)

    return SkillRecord(
        name=name,
        description=description,
        when_to_use=when_to_use,
        indexed_text=indexed_text,
        body=body,
        body_sanitized=body_sanitized,
        warnings=warnings,
        frontmatter=fm_data,
        hub_tags=[str(t) for t in hub_tags],
        trust=trust,
        path=str(path),
        scope=scope,
        disable_model_invocation=disable_invoke,
        bundled_files=bundled_files,
    )


def find_skill_files(roots: list[Path]) -> list[Path]:
    """Walk roots, return all SKILL.md paths."""
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            logger.debug("Skill root not found: %s", root)
            continue
        for skill_md in root.rglob("SKILL.md"):
            resolved = skill_md.resolve()
            if resolved in seen:
                continue
            if _is_in_excluded_dir(resolved):
                continue
            seen.add(resolved)
            found.append(resolved)
    logger.info("Discovered %d SKILL.md files", len(found))
    return found


_EXCLUDED_DIR_NAMES = frozenset(
    {"node_modules", ".venv", "venv", "env", "__pycache__", ".git", "dist", "build"}
)


def _is_in_excluded_dir(path: Path) -> bool:
    return any(part in _EXCLUDED_DIR_NAMES for part in path.parts)


def _scope_from_path(path: Path) -> str:
    """Categorize source: user / plugin / project / unknown."""
    home = Path.home()
    user_skills = home / ".claude" / "skills"
    plugins_root = home / ".claude" / "plugins" / "cache"

    try:
        if path.is_relative_to(user_skills):
            return f"user:{user_skills}"
        if path.is_relative_to(plugins_root):
            try:
                rel = path.relative_to(plugins_root)
                plugin_name = rel.parts[1] if len(rel.parts) > 1 else "?"
                return f"plugin:{plugin_name}"
            except (ValueError, IndexError):
                return "plugin:?"
    except (ValueError, OSError):
        pass

    parts = path.as_posix().split("/")
    for i, part in enumerate(parts):
        if part == ".claude" and i + 1 < len(parts) and parts[i + 1] == "skills":
            project_root = "/".join(parts[:i])
            return f"project:{project_root}"

    return "unknown"


def _collect_bundled_files(skill_md_path: Path) -> list[str]:
    """List files alongside SKILL.md (excluding SKILL.md itself).

    Used to surface 'bundled_files' in load_skill responses so agents know
    what extras the skill can reference.
    """
    parent = skill_md_path.parent
    if not parent.exists():
        return []
    out: list[str] = []
    for entry in sorted(parent.iterdir()):
        if entry.is_file() and entry.name != "SKILL.md":
            out.append(entry.name)
        elif entry.is_dir():
            out.append(f"{entry.name}/")
    return out
