"""File watcher - incremental re-index on SKILL.md changes.

Uses watchdog to observe configured skill roots. Each created / modified /
deleted / moved SKILL.md triggers a single-record update in AppContext,
keeping the index live without restarts.

Designed to run in a background thread so it can coexist with stdio MCP
transport (which holds the main thread).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from skills_radar.app import AppContext

logger = logging.getLogger(__name__)


class SkillFileHandler(FileSystemEventHandler):
    """Forwards SKILL.md events to AppContext.

    Filters out anything that isn't a SKILL.md file or that lives in an
    excluded directory (node_modules, .venv, .git, etc.). Coalesces rapid
    bursts (editor save spam) with a short debounce per path.
    """

    def __init__(self, app: AppContext, debounce_ms: int = 250) -> None:
        super().__init__()
        self.app = app
        self.debounce_seconds = debounce_ms / 1000.0
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # --- watchdog hooks ---

    def on_created(self, event: FileSystemEvent) -> None:
        if self._is_skill_event(event):
            self._schedule(Path(str(event.src_path)), action="upsert")

    def on_modified(self, event: FileSystemEvent) -> None:
        if self._is_skill_event(event):
            self._schedule(Path(str(event.src_path)), action="upsert")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if self._is_skill_event(event):
            self._schedule(Path(str(event.src_path)), action="delete")

    def on_moved(self, event: FileSystemEvent) -> None:
        if not self._is_skill_path(Path(str(event.src_path))):
            return
        self._schedule(Path(str(event.src_path)), action="delete")
        dest_path = Path(str(getattr(event, "dest_path", "")))
        if self._is_skill_path(dest_path):
            self._schedule(dest_path, action="upsert")

    # --- internals ---

    @staticmethod
    def _is_skill_event(event: FileSystemEvent) -> bool:
        if event.is_directory:
            return False
        return SkillFileHandler._is_skill_path(Path(str(event.src_path)))

    @staticmethod
    def _is_skill_path(path: Path) -> bool:
        from skills_radar.indexer import classify_md_path

        return classify_md_path(path) is not None

    def _schedule(self, path: Path, action: str) -> None:
        """Debounced dispatch - coalesces rapid editor saves."""
        key = f"{action}:{path}"
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()
            t = threading.Timer(self.debounce_seconds, self._dispatch, args=(path, action))
            t.daemon = True
            t.start()
            self._timers[key] = t

    def _dispatch(self, path: Path, action: str) -> None:
        try:
            if action == "upsert":
                self.app.handle_change_upsert(path)
            elif action == "delete":
                self.app.handle_change_delete(path)
        except Exception:
            logger.exception("Watcher dispatch failed for %s (%s)", path, action)


class WatcherService:
    """Owns the watchdog Observer + handler. Start/stop as a unit."""

    def __init__(self, app: AppContext) -> None:
        self.app = app
        self._observer: Observer | None = None  # type: ignore[type-arg]
        self._handler = SkillFileHandler(app)

    def start(self) -> None:
        if self._observer is not None:
            logger.debug("Watcher already running")
            return

        observer: Observer = Observer()  # type: ignore[type-arg]
        watched: list[Path] = []
        for raw in self.app.config.paths:
            root = Path(raw).expanduser()
            if not root.exists():
                logger.debug("Watcher: path does not exist, skipping: %s", root)
                continue
            observer.schedule(self._handler, str(root), recursive=True)
            watched.append(root)
        if not watched:
            logger.warning("Watcher: no valid paths to observe - running idle")
        else:
            logger.info("Watcher observing %d roots", len(watched))
            for w in watched:
                logger.debug("  → %s", w)
        observer.start()
        self._observer = observer

    def stop(self, timeout: float = 2.0) -> None:
        observer = self._observer
        if observer is None:
            return
        observer.stop()
        observer.join(timeout=timeout)
        self._observer = None
        logger.info("Watcher stopped")
