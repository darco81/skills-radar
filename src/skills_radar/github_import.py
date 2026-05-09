"""Import SKILL.md collections from public GitHub repos.

Use case: pull `awesome-agent-skills` or similar curated collection
into your skills-radar instance. Skills land in UNTRUSTED tier by
default - agents must explicitly opt in to load them, and
sanitization runs the same pipeline as for first-party skills.

Workflow:
1. Shallow git clone the repo into a temporary directory.
2. Find every SKILL.md under the configured subdirectory (default
   scans whole tree).
3. Copy each SKILL.md and its sibling files into a persistent
   location: ~/.local/share/skills-radar/imported/<repo-slug>/<rel-path>/
   so the skills survive after the clone is removed.
4. Cleanup the temp clone.

The persistent path becomes the new `path` for the skill record -
load_skill returns the imported file. Trust tier is UNTRUSTED unless
the user later promotes the path explicitly.

Returns a summary of imported / skipped / errored skills for the
caller (CLI) to display.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_IMPORT_ROOT = Path("~/.local/share/skills-radar/imported").expanduser()


@dataclass
class ImportResult:
    repo_slug: str
    imported: list[str] = field(default_factory=list)  # skill names successfully imported
    skipped: list[str] = field(default_factory=list)  # filename:reason
    errors: list[str] = field(default_factory=list)  # filename:exc

    @property
    def import_root(self) -> Path:
        return DEFAULT_IMPORT_ROOT / self.repo_slug


_REPO_RE = re.compile(r"^(?P<org>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$")


def _slugify(repo_spec: str) -> str:
    """Turn 'org/repo' or full URL into safe filesystem name."""
    m = _REPO_RE.match(repo_spec)
    if m:
        return f"{m.group('org')}--{m.group('repo')}"
    # URL form
    spec = repo_spec.rstrip("/").removesuffix(".git")
    parts = spec.rsplit("/", 2)
    if len(parts) >= 2:
        return f"{parts[-2]}--{parts[-1]}"
    return repo_spec.replace("/", "--").replace(":", "-")


def _resolve_repo_url(repo_spec: str) -> str:
    """Accept either 'org/repo' or full URL; normalize to a clone URL."""
    m = _REPO_RE.match(repo_spec)
    if m:
        return f"https://github.com/{m.group('org')}/{m.group('repo')}.git"
    if repo_spec.startswith(("http://", "https://", "git@", "git://")):
        return repo_spec
    msg = f"Cannot parse repo spec: {repo_spec!r}. Use 'org/repo' or a full URL."
    raise ValueError(msg)


def import_github_repo(
    repo_spec: str,
    *,
    branch: str = "main",
    subpath: str = ".",
    import_root: Path = DEFAULT_IMPORT_ROOT,
    yes: bool = False,
    dry_run: bool = False,
) -> ImportResult:
    """Clone a public repo, find SKILL.md files, copy to persistent storage.

    Args:
        repo_spec: 'org/repo' or full git URL.
        branch: branch / tag to clone.
        subpath: only scan SKILL.md under this subdirectory of the repo.
        import_root: persistent destination root.
        yes: auto-confirm import for every found skill (no prompt).
        dry_run: list candidates without copying anything.

    Returns:
        ImportResult with imported / skipped / errored lists.
    """
    repo_url = _resolve_repo_url(repo_spec)
    slug = _slugify(repo_spec)
    target_root = import_root.expanduser() / slug
    result = ImportResult(repo_slug=slug)

    with tempfile.TemporaryDirectory(prefix="skills-radar-import-") as tmp:
        clone_dir = Path(tmp) / slug
        try:
            subprocess.run(  # noqa: S603, S607 - git in PATH; repo_url scheme-validated above
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    branch,
                    "--single-branch",
                    repo_url,
                    str(clone_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            msg = "`git` command not found in PATH. Install git to use import-github."
            raise RuntimeError(msg) from exc
        except subprocess.CalledProcessError as exc:
            msg = f"git clone failed for {repo_url}: {exc.stderr.strip()[:200]}"
            raise RuntimeError(msg) from exc
        except subprocess.TimeoutExpired as exc:
            msg = f"git clone timed out after 120s for {repo_url}"
            raise RuntimeError(msg) from exc

        scan_dir = clone_dir / subpath
        if not scan_dir.exists():
            msg = f"Subpath {subpath!r} not found in {repo_url}@{branch}"
            raise RuntimeError(msg)

        candidates = sorted(scan_dir.rglob("SKILL.md"))
        if not candidates:
            return result

        for skill_md in candidates:
            rel = skill_md.relative_to(clone_dir)
            skill_dir_rel = rel.parent

            if not yes and not dry_run:
                # CLI is responsible for prompting; library mode requires yes=True
                # to actually copy. Fail fast for caller awareness.
                msg = (
                    "Non-interactive call without yes=True - set yes=True for bulk "
                    "import or dry_run=True to preview."
                )
                raise RuntimeError(msg)

            if dry_run:
                result.imported.append(str(rel))
                continue

            try:
                src_dir = skill_md.parent
                dst_dir = target_root / skill_dir_rel
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                # Copy the whole skill directory (sibling files included for sandbox)
                shutil.copytree(src_dir, dst_dir)
                result.imported.append(str(rel))
                logger.info("Imported %s → %s", rel, dst_dir)
            except (OSError, shutil.Error) as exc:
                result.errors.append(f"{rel}:{exc}")

    return result
