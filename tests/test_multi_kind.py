"""Multi-kind indexing: agents and commands alongside skills."""

from __future__ import annotations

from pathlib import Path

from skills_radar.indexer import (
    classify_md_path,
    find_resource_files,
    parse_skill_file,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


AGENT_MD = """---
name: qa-reporter
description: QA report generator. Builds ADF reports and queues them to Jira.
tools: Read, Bash
---

# QA Reporter

Body here.
"""

COMMAND_WITH_FM = """---
description: Build graph.json for the current repo.
---

Step one. Step two.
"""

COMMAND_LEGACY = """# Perf Report

Generate a performance report from collected findings.
"""


class TestClassify:
    def test_skill_md(self):
        assert classify_md_path(Path("/skills/personal/foo/SKILL.md")) == "skill"

    def test_agent(self):
        assert classify_md_path(Path("/skills/personal-extra/agents/qa.md")) == "agent"

    def test_command_nested(self):
        assert (
            classify_md_path(Path("/skills/projects/x/commands/perf/report.md"))
            == "command"
        )

    def test_plain_md_ignored(self):
        assert classify_md_path(Path("/skills/projects/x/notes/readme.md")) is None

    def test_excluded_dir(self):
        assert classify_md_path(Path("/skills/x/node_modules/agents/a.md")) is None

    def test_non_md(self):
        assert classify_md_path(Path("/skills/x/agents/a.txt")) is None


class TestParseKinds:
    def test_agent_name_from_frontmatter(self, tmp_path):
        p = _write(tmp_path / "agents" / "qa-reporter.md", AGENT_MD)
        rec = parse_skill_file(p, trusted_paths=[tmp_path], kind="agent")
        assert rec is not None
        assert rec.kind == "agent"
        assert rec.name == "qa-reporter"
        assert rec.uid == "agent:qa-reporter"

    def test_command_with_frontmatter_name_from_filename(self, tmp_path):
        p = _write(tmp_path / "commands" / "brain-extract.md", COMMAND_WITH_FM)
        rec = parse_skill_file(p, trusted_paths=[tmp_path], kind="command")
        assert rec is not None
        assert rec.name == "brain-extract"
        assert rec.uid == "cmd:brain-extract"
        assert "graph.json" in rec.description

    def test_legacy_command_without_frontmatter(self, tmp_path):
        p = _write(tmp_path / "commands" / "perf-report.md", COMMAND_LEGACY)
        rec = parse_skill_file(p, trusted_paths=[tmp_path], kind="command")
        assert rec is not None
        assert rec.name == "perf-report"
        assert rec.description == "Perf Report"

    def test_skill_without_frontmatter_still_rejected(self, tmp_path):
        p = _write(tmp_path / "foo" / "SKILL.md", "no frontmatter at all")
        rec = parse_skill_file(p, trusted_paths=[tmp_path], kind="skill")
        assert rec is None

    def test_skill_name_defaults_to_dir(self, tmp_path):
        p = _write(
            tmp_path / "my-skill" / "SKILL.md",
            "---\ndescription: does things\n---\n\nBody.\n",
        )
        rec = parse_skill_file(p, trusted_paths=[tmp_path], kind="skill")
        assert rec is not None
        assert rec.name == "my-skill"
        assert rec.uid == "my-skill"


class TestRootAnchoring:
    def test_nested_command_dir_accepted(self, tmp_path):
        # Claude Code namespaces nested commands: commands/perf/report.md → /perf:report
        assert (
            classify_md_path(tmp_path / "commands" / "perf" / "report.md", root=tmp_path)
            == "command"
        )

    def test_claude_anchored_deep_project_accepted(self, tmp_path):
        p = tmp_path / "projects" / "x" / ".claude" / "commands" / "deploy.md"
        assert classify_md_path(p, root=tmp_path) == "command"

    def test_deep_unanchored_src_tree_rejected(self, tmp_path):
        p = tmp_path / "repo" / "src" / "lib" / "commands" / "util.md"
        assert classify_md_path(p, root=tmp_path) is None

    def test_plugin_cache_layout_accepted(self, tmp_path):
        p = tmp_path / "plugins" / "market" / "plug" / "1.0.0" / "agents" / "a.md"
        assert classify_md_path(p, root=tmp_path) == "agent"

    def test_without_root_stays_shape_only(self, tmp_path):
        p = tmp_path / "repo" / "src" / "lib" / "commands" / "util.md"
        assert classify_md_path(p) == "command"

    def test_uppercase_stem_lowercased(self, tmp_path):
        p = _write(tmp_path / "agents" / "QA-Reporter.md", AGENT_MD.replace("name: qa-reporter\n", ""))
        rec = parse_skill_file(p, trusted_paths=[tmp_path], kind="agent")
        assert rec is not None
        assert rec.name == "qa-reporter"


class TestWatcherBackend:
    def test_polling_backend_selected(self):
        import pytest

        pytest.importorskip("watchdog")
        from skills_radar.config import Config, WatcherConfig
        from skills_radar.watcher import WatcherService
        from watchdog.observers.polling import PollingObserver

        class _StubApp:
            config = Config(watcher=WatcherConfig(enabled=True, backend="polling", poll_interval_s=5))

        svc = WatcherService(_StubApp())
        assert isinstance(svc._make_observer(), PollingObserver)

    def test_native_backend_default(self):
        import pytest

        pytest.importorskip("watchdog")
        from skills_radar.config import Config
        from skills_radar.watcher import WatcherService
        from watchdog.observers.polling import PollingObserver

        class _StubApp:
            config = Config()

        svc = WatcherService(_StubApp())
        assert not isinstance(svc._make_observer(), PollingObserver)

    def test_unknown_backend_rejected(self):
        import pytest
        from skills_radar.config import WatcherConfig

        with pytest.raises(ValueError, match="watcher.backend"):
            WatcherConfig(backend="fsevents")


class TestDiscovery:
    def test_find_resource_files_mixed_tree(self, tmp_path):
        _write(tmp_path / "skills" / "alpha" / "SKILL.md", "---\nname: alpha\ndescription: a\n---\nx")
        _write(tmp_path / "agents" / "beta.md", AGENT_MD)
        _write(tmp_path / "commands" / "gamma.md", COMMAND_LEGACY)
        _write(tmp_path / "README.md", "# ignored")
        _write(tmp_path / "repo" / "a" / "b" / "commands" / "junk.md", COMMAND_LEGACY)

        found = find_resource_files([tmp_path])
        kinds = sorted(kind for _, kind in found)
        assert kinds == ["agent", "command", "skill"]
