"""Tests for mini_index.generate_mini_index."""

from __future__ import annotations

from pathlib import Path

from skill_radar.mini_index import _csv_to_list, _first_sentence, generate_mini_index


def test_first_sentence_clips_at_period():
    text = "This does X. And then Y."
    out = _first_sentence(text, max_chars=80)
    assert out == "This does X."


def test_first_sentence_truncates_over_limit():
    text = "x" * 200
    out = _first_sentence(text, max_chars=50)
    assert len(out) <= 50
    assert out.endswith("…")


def test_first_sentence_handles_empty():
    assert _first_sentence("", 80) == "-"
    assert _first_sentence("   \n  ", 80) == "-"


def test_csv_to_list():
    assert _csv_to_list("") == []
    assert _csv_to_list("a") == ["a"]
    assert _csv_to_list("a,b, c , d") == ["a", "b", "c", "d"]


def test_generate_mini_index_grouping_by_hub_tags(tmp_path: Path):
    skills = [
        {
            "id": "a11y-orchestrator",
            "metadata": {
                "description": "Full WCAG audit dispatcher.",
                "hub_tags": "a11y,wcag",
            },
            "document": "...",
        },
        {
            "id": "perf-vue-runtime",
            "metadata": {
                "description": "Vue runtime perf audit.",
                "hub_tags": "perf,vue",
            },
            "document": "...",
        },
        {
            "id": "wcag-audit",
            "metadata": {
                "description": "WCAG 2.2 AA audit pipeline.",
                "hub_tags": "a11y,wcag",
            },
            "document": "...",
        },
        {
            "id": "loose",
            "metadata": {"description": "No tags here.", "hub_tags": ""},
            "document": "...",
        },
    ]
    out = tmp_path / "INDEX.md"
    result = generate_mini_index(skills, output=out)
    assert result == out

    content = out.read_text()
    # Each skill must appear at least once
    assert "a11y-orchestrator" in content
    assert "perf-vue-runtime" in content
    assert "wcag-audit" in content
    assert "loose" in content

    # Categories should appear
    assert "## a11y" in content
    assert "## wcag" in content
    assert "## perf" in content
    assert "## vue" in content
    assert "## uncategorized" in content

    # Multi-tag skills appear under both categories
    a11y_section = content.split("## a11y")[1].split("## ")[0]
    assert "a11y-orchestrator" in a11y_section
    assert "wcag-audit" in a11y_section


def test_generate_mini_index_grouping_by_scope(tmp_path: Path):
    skills = [
        {
            "id": "a",
            "metadata": {"description": "A.", "scope": "user:/Users/dariusz/.claude/skills"},
            "document": "...",
        },
        {
            "id": "b",
            "metadata": {"description": "B.", "scope": "plugin:huggingface-skills"},
            "document": "...",
        },
    ]
    out = tmp_path / "INDEX.md"
    generate_mini_index(skills, output=out, group_by="scope")
    content = out.read_text()
    assert "## user" in content
    assert "## plugin" in content


def test_generate_mini_index_writes_header(tmp_path: Path):
    out = tmp_path / "INDEX.md"
    generate_mini_index([], output=out)
    content = out.read_text()
    assert "AUTO-GENERATED" in content
    assert "Skills available" in content
    assert "Total: 0 skills" in content
