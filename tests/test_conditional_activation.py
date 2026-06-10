"""Conditional activation - Hermes-inspired, agentskills.io metadata convention.

Frontmatter fields read from `metadata.radar.*` (namespaced per the
agentskills.io convention) with top-level fallback:
- platforms: skill active only on matching host platform (gated at index time)
- requires_tools / fallback_for_tools: stored + exposed in search results so
  the consuming agent can apply environment policy (server can't know client tools)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from skills_radar.app import AppContext, _detect_platform, _platform_matches
from skills_radar.config import Config, StoreConfig, TrustConfig
from skills_radar.indexer import parse_skill_file
from skills_radar.mcp_server import _match_to_entry


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Parser - metadata.radar.* namespace + top-level fallback
# ---------------------------------------------------------------------------


def test_parse_radar_namespace_fields(tmp_path: Path):
    skill = _write(
        tmp_path / "gated" / "SKILL.md",
        """\
        ---
        name: gated-skill
        description: A conditionally-activated skill.
        metadata:
          radar:
            platforms: [macos, linux]
            requires_tools: [figma-mcp]
            fallback_for_tools: [web-search]
            hub-tags: [qa]
        ---

        body
        """,
    )
    rec = parse_skill_file(skill, trusted_paths=[tmp_path])
    assert rec is not None
    assert rec.platforms == ["macos", "linux"]
    assert rec.requires_tools == ["figma-mcp"]
    assert rec.fallback_for_tools == ["web-search"]
    assert rec.hub_tags == ["qa"]


def test_parse_top_level_fallback(tmp_path: Path):
    skill = _write(
        tmp_path / "toplevel" / "SKILL.md",
        """\
        ---
        name: toplevel-skill
        description: Fields at top level, no metadata namespace.
        platforms: [windows]
        requires_tools: [powershell]
        hub-tags: [ops]
        ---

        body
        """,
    )
    rec = parse_skill_file(skill, trusted_paths=[tmp_path])
    assert rec is not None
    assert rec.platforms == ["windows"]
    assert rec.requires_tools == ["powershell"]
    assert rec.fallback_for_tools == []
    assert rec.hub_tags == ["ops"]


def test_parse_radar_namespace_wins_over_top_level(tmp_path: Path):
    skill = _write(
        tmp_path / "both" / "SKILL.md",
        """\
        ---
        name: both-skill
        description: Namespaced value must win.
        platforms: [windows]
        metadata:
          radar:
            platforms: [macos]
        ---

        body
        """,
    )
    rec = parse_skill_file(skill, trusted_paths=[tmp_path])
    assert rec is not None
    assert rec.platforms == ["macos"]


def test_parse_defaults_empty(tmp_path: Path):
    skill = _write(
        tmp_path / "plain" / "SKILL.md",
        """\
        ---
        name: plain-skill
        description: No conditional fields at all.
        ---

        body
        """,
    )
    rec = parse_skill_file(skill, trusted_paths=[tmp_path])
    assert rec is not None
    assert rec.platforms == []
    assert rec.requires_tools == []
    assert rec.fallback_for_tools == []


# ---------------------------------------------------------------------------
# Platform detection + matching (pure functions)
# ---------------------------------------------------------------------------


def test_platform_matches():
    assert _platform_matches([], "macos")  # no constraint = all platforms
    assert _platform_matches(["macos", "linux"], "macos")
    assert not _platform_matches(["windows"], "macos")
    assert _platform_matches(["MacOS"], "macos")  # case-insensitive


def test_detect_platform_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert _detect_platform() == "macos"
    monkeypatch.setattr("sys.platform", "win32")
    assert _detect_platform() == "windows"
    monkeypatch.setattr("sys.platform", "linux")
    assert _detect_platform() == "linux"


# ---------------------------------------------------------------------------
# Index-time gating (AppContext) - module-scoped, heavy embedder loads once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gated_ctx(tmp_path_factory: pytest.TempPathFactory) -> AppContext:
    base = tmp_path_factory.mktemp("radar-gating")
    skills = base / "skills"
    _write(
        skills / "everywhere" / "SKILL.md",
        """\
        ---
        name: everywhere-skill
        description: No platform constraint, always indexed.
        ---

        body
        """,
    )
    _write(
        skills / "mac-only" / "SKILL.md",
        """\
        ---
        name: mac-only-skill
        description: Mac-only skill with tool conditions.
        metadata:
          radar:
            platforms: [macos]
            requires_tools: [figma-mcp]
        ---

        body
        """,
    )
    _write(
        skills / "win-only" / "SKILL.md",
        """\
        ---
        name: win-only-skill
        description: Windows-only, must be gated out on macos.
        metadata:
          radar:
            platforms: [windows]
        ---

        body
        """,
    )
    cfg = Config(
        paths=[skills],
        store=StoreConfig(path=base / "store"),
        trust=TrustConfig(trusted_paths=[skills]),
        platform="macos",
    )
    ctx = AppContext(cfg)
    ctx.reindex(rebuild=True)
    return ctx


def test_reindex_gates_by_platform(gated_ctx: AppContext):
    names = {i["id"] for i in gated_ctx.store.list_all()}
    assert names == {"everywhere-skill", "mac-only-skill"}


def test_watcher_upsert_gates_by_platform(gated_ctx: AppContext, tmp_path: Path):
    path = _write(
        tmp_path / "hot-win" / "SKILL.md",
        """\
        ---
        name: hot-win-skill
        description: Hot-added windows-only skill.
        platforms: [windows]
        ---

        body
        """,
    )
    gated_ctx.handle_change_upsert(path)
    assert gated_ctx.store.get("hot-win-skill") is None


def test_metadata_carries_conditional_fields(gated_ctx: AppContext):
    stored = gated_ctx.store.get("mac-only-skill")
    assert stored is not None
    meta = stored["metadata"]
    # ChromaDB coerces lists to CSV strings
    assert meta.get("platforms") == "macos"
    assert meta.get("requires_tools") == "figma-mcp"


# ---------------------------------------------------------------------------
# Search-response shaping (pure helper, no AppContext)
# ---------------------------------------------------------------------------


def _meta(**overrides):
    base = {
        "description": "d",
        "when_to_use": "w",
        "trust": "user",
        "scope": "user",
        "hub_tags": "",
        "requires_tools": "",
        "fallback_for_tools": "",
    }
    base.update(overrides)
    return base


def test_search_entry_exposes_tool_conditions():
    m = {
        "name": "x",
        "score": 0.5,
        "metadata": _meta(hub_tags="qa,dev", requires_tools="figma-mcp"),
    }
    entry = _match_to_entry(m)
    assert entry["requires_tools"] == ["figma-mcp"]
    assert entry["fallback_for_tools"] == []
    assert entry["hub_tags"] == ["qa", "dev"]
    assert entry["name"] == "x"
    assert entry["score"] == 0.5


def test_search_entry_tolerates_list_metadata():
    """Qdrant keeps lists as-is in payload (no CSV coercion like ChromaDB)."""
    m = {
        "name": "y",
        "score": 0.9,
        "metadata": _meta(hub_tags=["qa"], requires_tools=["a", "b"], fallback_for_tools=[]),
    }
    entry = _match_to_entry(m)
    assert entry["hub_tags"] == ["qa"]
    assert entry["requires_tools"] == ["a", "b"]
    assert entry["fallback_for_tools"] == []
