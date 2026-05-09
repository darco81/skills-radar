"""Integration tests - end-to-end with real embedder + ChromaDB.

Slower than smoke tests (sentence-transformers loads ~5s on first run);
fixtures are scoped to the module so the heavy deps load once.
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from skills_radar.app import AppContext
from skills_radar.config import (
    Config,
    EmbedderConfig,
    RetrievalConfig,
    SanitizationConfig,
    StoreConfig,
    TransportConfig,
    TrustConfig,
)
from skills_radar.indexer import find_skill_files
from skills_radar.mini_index import generate_mini_index

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(
    path: Path,
    name: str,
    description: str,
    when_to_use: str = "",
    body: str = "Body content.",
    extra_frontmatter: dict[str, Any] | None = None,
) -> Path:
    """Write a minimal valid SKILL.md and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm: list[str] = [f"name: {name}", f"description: {description}"]
    if when_to_use:
        fm.append(f"when_to_use: |\n  {when_to_use}")
    if extra_frontmatter:
        for k, v in extra_frontmatter.items():
            if isinstance(v, list):
                fm.append(f"{k}:")
                fm.extend(f"  - {item}" for item in v)
            elif isinstance(v, bool):
                fm.append(f"{k}: {str(v).lower()}")
            else:
                fm.append(f"{k}: {v}")
    content = "---\n" + "\n".join(fm) + "\n---\n\n" + body + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _make_config(skills_root: Path, store_root: Path) -> Config:
    return Config(
        paths=[skills_root],
        embedder=EmbedderConfig(),
        store=StoreConfig(path=store_root),
        transport=TransportConfig(),
        retrieval=RetrievalConfig(),
        trust=TrustConfig(default_tier="user", trusted_paths=[skills_root]),
        sanitization=SanitizationConfig(),
    )


# ---------------------------------------------------------------------------
# Module-scoped fixtures - heavy embedder loads once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def integration_workspace(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("skills-radar-it")
    return base / "skills", base / "store"


@pytest.fixture(scope="module")
def app_context(integration_workspace: tuple[Path, Path]) -> AppContext:
    skills_root, store_root = integration_workspace
    skills_root.mkdir(parents=True, exist_ok=True)
    # Seed three skills BEFORE first AppContext build so reindex picks them up.
    _write_skill(
        skills_root / "wcag-audit" / "SKILL.md",
        name="wcag-audit-test",
        description="Run a WCAG 2.1 AA accessibility audit on a website.",
        when_to_use="Triggers: audit accessibility, check WCAG, a11y review.",
        extra_frontmatter={"hub-tags": ["a11y", "wcag"]},
    )
    _write_skill(
        skills_root / "perf-vue" / "SKILL.md",
        name="perf-vue-test",
        description="Audit Vue 3 runtime performance - re-renders, watcher leaks, INP.",
        when_to_use="Triggers: Vue slow, memory leak, watcher cleanup.",
        extra_frontmatter={"hub-tags": ["perf", "vue"]},
    )
    _write_skill(
        skills_root / "content" / "SKILL.md",
        name="content-writer-test",
        description="Draft brand content - LinkedIn posts, articles, case studies.",
        when_to_use="Triggers: write a post, draft article.",
        extra_frontmatter={"hub-tags": ["content"]},
    )

    cfg = _make_config(skills_root, store_root)
    ctx = AppContext(cfg)
    ctx.reindex(rebuild=True)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reindex_picks_up_seeded_skills(app_context: AppContext):
    assert app_context.store.count() == 3
    names = {item["id"] for item in app_context.store.list_all()}
    assert names == {"wcag-audit-test", "perf-vue-test", "content-writer-test"}


def test_search_wcag_query_finds_a11y_skill(app_context: AppContext):
    matches = app_context.hybrid_search("audit accessibility WCAG", top_k=3)
    assert len(matches) > 0
    assert matches[0]["name"] == "wcag-audit-test"
    assert matches[0]["score"] > 0.4


def test_search_vue_perf_query_finds_perf_skill(app_context: AppContext):
    matches = app_context.hybrid_search("Vue memory leak slow rendering", top_k=3)
    assert matches[0]["name"] == "perf-vue-test"


def test_search_content_query_finds_content_skill(app_context: AppContext):
    matches = app_context.hybrid_search("write a LinkedIn post", top_k=3)
    assert matches[0]["name"] == "content-writer-test"


def test_search_with_tag_filter(app_context: AppContext):
    matches = app_context.hybrid_search("audit", top_k=5, tags=["wcag"])
    names = [m["name"] for m in matches]
    assert "wcag-audit-test" in names
    # perf-vue-test has 'perf,vue' tags only - must NOT pass the wcag filter
    assert "perf-vue-test" not in names


def test_load_record_returns_full_skill(app_context: AppContext):
    record, meta = app_context.load_record("wcag-audit-test")
    assert record is not None
    assert record.name == "wcag-audit-test"
    assert "WCAG 2.1 AA" in record.description
    assert record.body_sanitized.strip().startswith("Body content")
    assert meta is not None
    assert meta.get("trust") == "trusted"


def test_load_record_unknown_returns_none(app_context: AppContext):
    record, meta = app_context.load_record("does-not-exist")
    assert record is None
    assert meta is None


def test_hot_reload_upsert_picks_up_new_skill(
    app_context: AppContext, integration_workspace: tuple[Path, Path]
):
    skills_root, _ = integration_workspace
    new_skill_dir = skills_root / "new-hot-skill"
    new_path = _write_skill(
        new_skill_dir / "SKILL.md",
        name="hot-reload-test",
        description="A freshly added skill for testing hot reload.",
        when_to_use="Triggers: hot reload test.",
    )
    app_context.handle_change_upsert(new_path)

    assert app_context.store.get("hot-reload-test") is not None
    matches = app_context.hybrid_search("hot reload test", top_k=3)
    assert any(m["name"] == "hot-reload-test" for m in matches)


def test_hot_reload_delete_removes_skill(
    app_context: AppContext, integration_workspace: tuple[Path, Path]
):
    skills_root, _ = integration_workspace
    target_dir = skills_root / "ephemeral-skill"
    target_path = _write_skill(
        target_dir / "SKILL.md",
        name="ephemeral-test",
        description="Temporary skill that will be deleted.",
    )
    app_context.handle_change_upsert(target_path)
    assert app_context.store.get("ephemeral-test") is not None

    target_path.unlink()
    app_context.handle_change_delete(target_path)
    assert app_context.store.get("ephemeral-test") is None


def test_disable_model_invocation_skipped(
    app_context: AppContext, integration_workspace: tuple[Path, Path]
):
    skills_root, _ = integration_workspace
    skill_path = _write_skill(
        skills_root / "manual-only" / "SKILL.md",
        name="manual-only-test",
        description="Manual invocation only, never auto.",
        extra_frontmatter={"disable-model-invocation": True},
    )
    # handle_change_upsert respects the flag
    app_context.handle_change_upsert(skill_path)
    assert app_context.store.get("manual-only-test") is None


def test_load_record_fresh_read_after_edit(
    app_context: AppContext, integration_workspace: tuple[Path, Path]
):
    """Verify that load_record re-reads from disk so live edits surface."""
    skills_root, _ = integration_workspace
    skill_path = _write_skill(
        skills_root / "edit-target" / "SKILL.md",
        name="edit-target-test",
        description="Original description.",
        body="Original body content.",
    )
    app_context.handle_change_upsert(skill_path)

    rec1, _ = app_context.load_record("edit-target-test")
    assert rec1 is not None
    assert "Original body content" in rec1.body_sanitized

    # Modify file directly (simulating user edit between calls)
    time.sleep(0.05)
    skill_path.write_text(
        textwrap.dedent(
            """\
            ---
            name: edit-target-test
            description: Original description.
            ---

            Updated body content for fresh-read verification.
            """
        )
    )

    rec2, _ = app_context.load_record("edit-target-test")
    assert rec2 is not None
    assert "Updated body content" in rec2.body_sanitized
    assert "Original body content" not in rec2.body_sanitized


def test_mini_index_generation_full_pipeline(app_context: AppContext, tmp_path: Path):
    items = app_context.store.list_all()
    out = tmp_path / "INDEX.md"
    generate_mini_index(items, output=out)
    content = out.read_text()
    # Each seeded skill must appear under its tag category
    assert "## a11y" in content
    assert "## perf" in content
    assert "## content" in content
    assert "wcag-audit-test" in content
    assert "perf-vue-test" in content
    assert "content-writer-test" in content


def test_find_skill_files_skips_excluded_dirs(integration_workspace: tuple[Path, Path]):
    skills_root, _ = integration_workspace
    excluded = skills_root / "node_modules" / "junk"
    _write_skill(excluded / "SKILL.md", name="junk", description="Should be excluded.")
    found = find_skill_files([skills_root])
    paths = [str(p) for p in found]
    assert not any("node_modules" in p for p in paths)


def test_dedup_higher_trust_wins(tmp_path: Path):
    """Same skill name in two locations - higher-priority trust tier wins."""
    skills_root = tmp_path / "skills"
    untrusted_root = tmp_path / "external"
    store_root = tmp_path / "store"

    _write_skill(
        skills_root / "shared" / "SKILL.md",
        name="shared-name",
        description="USER tier version.",
    )
    _write_skill(
        untrusted_root / "shared" / "SKILL.md",
        name="shared-name",
        description="UNTRUSTED tier version.",
    )

    cfg = Config(
        paths=[skills_root, untrusted_root],
        store=StoreConfig(path=store_root),
        trust=TrustConfig(default_tier="user", trusted_paths=[skills_root]),
    )
    ctx = AppContext(cfg)
    ctx.reindex(rebuild=True)

    record, _ = ctx.load_record("shared-name")
    assert record is not None
    assert "USER tier version" in record.description
    assert ctx.store.count() == 1
