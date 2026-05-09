"""Read-only sandbox for SKILL.md bundled files.

When `load_skill(name, sandbox=True)` is called, the bundled files
referenced one directory level deep from SKILL.md are read, validated,
and returned as a `sandboxed_files` dict in the response. The agent
gets the content without filesystem access of its own.

Safety constraints:
- Whitelist of safe extensions (text-only formats - never binaries,
  never executables, never archive containers)
- Max total payload size (default 256 KB) - prevents DoS via giant
  bundled file
- Per-file size cap (default 64 KB) - same reasoning per artifact
- No symlinks - symlinks are rejected (could escape the skill dir)
- No path traversal - files must be in the SAME directory as
  SKILL.md, not deeper / not relative-up

Trust tier matters here: even sandboxed read-only content from an
UNTRUSTED skill is still adversarial input, sanitized via the same
pipeline as SKILL.md body. Sandbox only changes whether the agent
sees the file content; it does NOT make UNTRUSTED content safe.
"""

from __future__ import annotations

import logging
from pathlib import Path

from skills_radar.sanitize import sanitize_body

logger = logging.getLogger(__name__)

# Safe extensions = pure text we can sanitize the same way as SKILL.md body.
# Explicitly excluded: binaries (.so, .dylib, .exe), archives (.zip, .tar),
# images (.png, .jpg), PDFs, anything with active content (.html with scripts).
SAFE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".vue",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".env.example",
        ".sql",
        ".graphql",
        ".gql",
        ".css",
        ".scss",
        ".less",
        ".log",
        ".csv",
        ".tsv",
        ".lock",
        ".gitignore",
        ".dockerignore",
        ".prettierrc",
        ".eslintrc",
    }
)

DEFAULT_MAX_PER_FILE_KB = 64
DEFAULT_MAX_TOTAL_KB = 256


def is_safe_extension(filename: str) -> bool:
    """Whitelist check. Multi-suffix files (e.g. `setup.cfg.bak`) are
    examined against the FULL trailing token after the last `.`."""
    name = filename.lower()
    if name.startswith(".") and "." in name[1:]:
        # e.g. `.env.example` - check the longest dotted suffix
        for ext in SAFE_EXTENSIONS:
            if name.endswith(ext):
                return True
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    return suffix in SAFE_EXTENSIONS


def sandbox_bundled_files(
    skill_md_path: Path,
    bundled_files: list[str],
    *,
    max_per_file_kb: int = DEFAULT_MAX_PER_FILE_KB,
    max_total_kb: int = DEFAULT_MAX_TOTAL_KB,
    strip_live_exec: bool = False,
) -> tuple[dict[str, str], list[str]]:
    """Read bundled files from disk with full safety validation.

    Returns:
        (sandboxed_files, warnings) where:
        - sandboxed_files: filename → sanitized content (UTF-8 string)
        - warnings: list of skipped files with reasons (size, extension,
          symlink, traversal, encoding, etc.)
    """
    skill_dir = skill_md_path.parent.resolve()
    sandboxed: dict[str, str] = {}
    warnings: list[str] = []
    total_bytes = 0
    max_total_bytes = max_total_kb * 1024
    max_per_file_bytes = max_per_file_kb * 1024

    for entry in bundled_files:
        # Directories are listed as "name/" - skip them in sandbox mode
        if entry.endswith("/"):
            warnings.append(f"skipped:{entry}:is_directory")
            continue

        if not is_safe_extension(entry):
            warnings.append(f"skipped:{entry}:unsafe_extension")
            continue

        candidate = skill_dir / entry
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            warnings.append(f"skipped:{entry}:resolve_failed")
            continue

        # Path traversal - must be a direct child of skill_dir
        try:
            if resolved.parent != skill_dir:
                warnings.append(f"skipped:{entry}:path_traversal")
                continue
        except (ValueError, OSError):
            warnings.append(f"skipped:{entry}:invalid_path")
            continue

        if not resolved.exists():
            warnings.append(f"skipped:{entry}:not_found")
            continue

        if resolved.is_symlink() or candidate.is_symlink():
            warnings.append(f"skipped:{entry}:symlink_rejected")
            continue

        if not resolved.is_file():
            warnings.append(f"skipped:{entry}:not_a_file")
            continue

        try:
            size = resolved.stat().st_size
        except OSError as exc:
            warnings.append(f"skipped:{entry}:stat_failed:{exc}")
            continue

        if size > max_per_file_bytes:
            warnings.append(f"skipped:{entry}:per_file_size_exceeded:{size}>{max_per_file_bytes}")
            continue

        if total_bytes + size > max_total_bytes:
            warnings.append(
                f"skipped:{entry}:total_budget_exhausted:{total_bytes + size}>{max_total_bytes}"
            )
            continue

        try:
            raw = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            warnings.append(f"skipped:{entry}:utf8_decode_failed:{exc}")
            continue

        # Sanitize same way as SKILL.md body
        sanitized, body_warnings = sanitize_body(raw, strip_live_exec=strip_live_exec)
        if body_warnings:
            warnings.extend(f"sandbox:{entry}:{w}" for w in body_warnings)

        sandboxed[entry] = sanitized
        total_bytes += size
        logger.debug("Sandboxed %s (%d bytes) from %s", entry, size, skill_md_path)

    return sandboxed, warnings
