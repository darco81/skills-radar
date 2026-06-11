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

from skills_radar.sanitize import (
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
    """Parsed + sanitized resource record (skill / agent / command)."""

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
    platforms: list[str] = field(default_factory=list)
    requires_tools: list[str] = field(default_factory=list)
    fallback_for_tools: list[str] = field(default_factory=list)
    kind: str = "skill"  # 'skill' | 'agent' | 'command'

    @property
    def uid(self) -> str:
        """Store ID. Skills keep their bare name (backwards-compatible);
        agents/commands are namespaced so a skill and an agent may share
        a name without colliding."""
        if self.kind == "skill":
            return self.name
        prefix = "agent" if self.kind == "agent" else "cmd"
        return f"{prefix}:{self.name}"


def parse_skill_file(
    path: Path,
    *,
    trusted_paths: list[Path],
    max_size_kb: int = 64,
    strip_live_exec: bool = False,
    reject_untrusted_on_injection: bool = False,
    kind: str = "skill",
) -> SkillRecord | None:
    """Parse one resource file (SKILL.md / agent .md / command .md).

    Returns None if invalid (logged). Strictness varies by kind:
    skills and agents require frontmatter with a description; commands
    may have no frontmatter at all (legacy format) - name then comes
    from the filename and description from the first body line.

    Injection-pattern matches normally only flag (warnings on the record);
    with `reject_untrusted_on_injection` an UNTRUSTED-tier file carrying an
    injection warning is rejected instead. Other tiers are never rejected.
    """
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
        if kind != "command":
            logger.debug("No YAML frontmatter in %s", path)
            return None
        fm_data: dict = {}
        body = text
    else:
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
    if not name:
        # Claude Code convention: name defaults to the directory name for
        # skills, and to the filename for agents/commands. Lowercased so
        # mixed-case filenames don't fail name validation.
        name = (path.parent.name if kind == "skill" else path.stem).lower()
    if not validate_name(name):
        logger.warning("Invalid or reserved name %r in %s", name, path)
        return None

    description = (fm_data.get("description") or "").strip()
    if not description and kind == "command":
        description = _first_body_line(body)
    when_to_use = (fm_data.get("when_to_use") or "").strip()
    radar_meta = _radar_meta(fm_data)
    hub_tags = _list_field(radar_meta, fm_data, "hub-tags", "hub_tags")
    platforms = [p.lower() for p in _list_field(radar_meta, fm_data, "platforms")]
    requires_tools = _list_field(radar_meta, fm_data, "requires_tools", "requires-tools")
    fallback_for_tools = _list_field(
        radar_meta, fm_data, "fallback_for_tools", "fallback-for-tools"
    )
    disable_invoke = bool(fm_data.get("disable-model-invocation", False))

    indexed_text = description
    if when_to_use:
        indexed_text = f"{indexed_text}\n\n{when_to_use}".strip()

    if not indexed_text:
        logger.warning("Empty description+when_to_use in %s", path)
        return None

    body_sanitized, warnings = sanitize_body(body, strip_live_exec=strip_live_exec)

    trust = determine_trust_tier(path, trusted_paths)
    if reject_untrusted_on_injection and trust is TrustTier.UNTRUSTED:
        injection_hits = [w for w in warnings if _is_injection_warning(w)]
        if injection_hits:
            logger.warning(
                "Rejecting UNTRUSTED resource with injection warnings %s: %s",
                injection_hits,
                path,
            )
            return None
    scope = _scope_from_path(path)
    bundled_files = _collect_bundled_files(path) if kind == "skill" else []

    return SkillRecord(
        kind=kind,
        name=name,
        description=description,
        when_to_use=when_to_use,
        indexed_text=indexed_text,
        body=body,
        body_sanitized=body_sanitized,
        warnings=warnings,
        frontmatter=fm_data,
        hub_tags=hub_tags,
        trust=trust,
        path=str(path),
        scope=scope,
        disable_model_invocation=disable_invoke,
        bundled_files=bundled_files,
        platforms=platforms,
        requires_tools=requires_tools,
        fallback_for_tools=fallback_for_tools,
    )


def _is_injection_warning(warning: str) -> bool:
    """True for sanitize_body warnings that indicate an injection hit
    (as opposed to e.g. live_exec_syntax_stripped)."""
    return (
        warning.startswith("injection_pattern_detected") or warning == "xml_injection_tags_detected"
    )


def _radar_meta(fm_data: dict) -> dict:
    """Return the `metadata.radar.*` namespace (agentskills.io convention,
    same pattern as Hermes' `metadata.hermes.*`). Callers fall back to
    top-level keys when a field is absent here."""
    meta = fm_data.get("metadata")
    if not isinstance(meta, dict):
        return {}
    radar = meta.get("radar")
    return radar if isinstance(radar, dict) else {}


def _list_field(radar_meta: dict, fm_data: dict, *keys: str) -> list[str]:
    """First list value found: namespaced keys win over top-level.

    Bare scalars coerce to single-item lists - `platforms: macos` is natural
    YAML and must gate, not silently fall open to 'no constraint'."""
    for source in (radar_meta, fm_data):
        for key in keys:
            val = source.get(key)
            if isinstance(val, (str, int, float)):
                val = [val]
            if isinstance(val, list):
                return [str(x).strip() for x in val if str(x).strip()]
    return []


def find_skill_files(roots: list[Path]) -> list[Path]:
    """Walk roots, return all SKILL.md paths."""
    return [p for p, kind in find_resource_files(roots) if kind == "skill"]


def classify_md_path(path: Path, root: Path | None = None) -> str | None:
    """Map a .md path to its resource kind, or None if not indexable.

    SKILL.md → skill; .md under an `agents/` dir → agent; .md under a
    `commands/` dir → command (nested command subdirs are valid - Claude
    Code namespaces them, e.g. `commands/perf/report.md` → /perf:report).

    When `root` is given, agent/command dirs must be *anchored* - directly
    under a `.claude` dir, inside the plugin cache, or at most two levels
    below the scan root (covers `<mount>/agents` and `projects/<x>/agents`
    bind-mount layouts). This stops arbitrary nested markdown (e.g.
    `some-repo/src/commands/util.md`) from being ingested.
    """
    if path.suffix.lower() != ".md":
        return None
    if _is_in_excluded_dir(path):
        return None
    if path.name == "SKILL.md":
        return "skill"
    try:
        parts = path.relative_to(root).parts[:-1] if root else path.parts[:-1]
    except ValueError:
        parts = path.parts[:-1]
    for marker, kind in (("agents", "agent"), ("commands", "command")):
        if marker not in parts:
            continue
        if root is None:
            return kind
        idx = parts.index(marker)
        anchored = (
            idx <= 2
            or ".claude" in parts[:idx]
            or parts[0] == "plugins"  # container plugin-cache mount (CC-managed layout)
        )
        return kind if anchored else None
    return None


def find_resource_files(roots: list[Path]) -> list[tuple[Path, str]]:
    """Walk roots, return (path, kind) for every indexable resource.

    Follows the same exclusion rules for all kinds. Symlinked files
    resolve before dedupe, so a skill reachable via two roots indexes once.
    """
    found: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    counts = {"skill": 0, "agent": 0, "command": 0}
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            logger.debug("Skill root not found: %s", root)
            continue
        for md in root.rglob("*.md"):
            kind = classify_md_path(md, root=root)
            if kind is None:
                continue
            try:
                resolved = md.resolve()
            except OSError:
                continue
            if resolved in seen or not resolved.exists():
                continue
            seen.add(resolved)
            found.append((resolved, kind))
            counts[kind] += 1
    logger.info(
        "Discovered %d resources (%d skills, %d agents, %d commands)",
        len(found),
        counts["skill"],
        counts["agent"],
        counts["command"],
    )
    return found


_EXCLUDED_DIR_NAMES = frozenset(
    {"node_modules", ".venv", "venv", "env", "__pycache__", ".git", "dist", "build"}
)


def _is_in_excluded_dir(path: Path) -> bool:
    return any(part in _EXCLUDED_DIR_NAMES for part in path.parts)


def _scope_from_path(path: Path) -> str:
    """Categorize source: user / plugin / project / unknown.

    Handles both host paths (~/.claude/...) and the Docker bind-mount
    layout (/skills/personal, /skills/plugins, /skills/projects/<name>).
    """
    posix = path.as_posix()

    # Docker bind-mount layout (container deployments)
    if posix.startswith("/skills/"):
        parts = posix.split("/")
        # ['', 'skills', '<mount>', ...]
        mount = parts[2] if len(parts) > 2 else "?"
        if mount.startswith("personal"):
            return "user"
        if mount == "plugins":
            # /skills/plugins/<marketplace>/<plugin>/...
            plugin_name = parts[4] if len(parts) > 4 else "?"
            return f"plugin:{plugin_name}"
        if mount == "projects":
            project = parts[3] if len(parts) > 3 else "?"
            return f"project:{project}"
        return "unknown"

    # Host layout
    home = Path.home()
    user_root = home / ".claude"
    plugins_root = user_root / "plugins" / "cache"

    try:
        if path.is_relative_to(plugins_root):
            try:
                rel = path.relative_to(plugins_root)
                plugin_name = rel.parts[1] if len(rel.parts) > 1 else "?"
                return f"plugin:{plugin_name}"
            except (ValueError, IndexError):
                return "plugin:?"
        for sub in ("skills", "agents", "commands"):
            if path.is_relative_to(user_root / sub):
                return "user"
    except (ValueError, OSError):
        pass

    parts = posix.split("/")
    for i, part in enumerate(parts):
        if part == ".claude" and i + 1 < len(parts) and parts[i + 1] in (
            "skills",
            "agents",
            "commands",
        ):
            project_root = "/".join(parts[:i])
            return f"project:{project_root}"

    return "unknown"


def _first_body_line(body: str) -> str:
    """First meaningful line of a body - description fallback for legacy
    commands that ship no frontmatter. Strips markdown heading markers."""
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:300]
    return ""


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
