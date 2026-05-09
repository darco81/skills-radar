"""Local opt-in usage telemetry. SQLite, no network.

Logs three event types:
- `search`: query, top1 score, top5 names, latency_ms
- `load`: skill_name, trust, body_len, latency_ms
- `index`: count, duration_ms, rebuild flag

Default disabled. Enable with `telemetry.enabled: true` in config.
Read with `skills-radar stats`. No remote telemetry, ever - file lives
under `~/.local/share/skills-radar/stats.db`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("~/.local/share/skills-radar/stats.db").expanduser()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
"""


class Telemetry:
    """Append-only SQLite event log. Thread-safe via per-call connections."""

    def __init__(self, *, enabled: bool = False, db_path: Path | None = None) -> None:
        self.enabled = enabled
        self.db_path = (db_path or DEFAULT_DB_PATH).expanduser()
        if self.enabled:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._conn() as conn:
                conn.executescript(_SCHEMA)
            logger.info("Telemetry enabled at %s", self.db_path)

    @contextmanager
    def _conn(self) -> Any:  # noqa: ANN401 - sqlite3 connection generator
        conn = sqlite3.connect(self.db_path, timeout=2.0)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def log(self, kind: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO events (ts, kind, payload) VALUES (?, ?, ?)",
                    (time.time(), kind, json.dumps(payload, default=str)),
                )
        except sqlite3.Error as exc:
            logger.warning("Telemetry log failed (%s): %s", kind, exc)

    # --- Convenience helpers, used at call sites --------------------------------

    def log_search(
        self,
        query: str,
        matches: list[dict[str, Any]],
        latency_ms: float,
        rewriter_used: bool = False,
    ) -> None:
        top1_score = float(matches[0]["score"]) if matches else 0.0
        top5_names = [m["name"] for m in matches[:5]]
        self.log(
            "search",
            {
                "query": query,
                "top1_score": top1_score,
                "top5_names": top5_names,
                "latency_ms": round(latency_ms, 2),
                "rewriter_used": rewriter_used,
                "n_matches": len(matches),
            },
        )

    def log_load(
        self,
        skill_name: str,
        *,
        trust: str,
        body_len: int,
        latency_ms: float,
        found: bool,
    ) -> None:
        self.log(
            "load",
            {
                "skill_name": skill_name,
                "trust": trust,
                "body_len": body_len,
                "latency_ms": round(latency_ms, 2),
                "found": found,
            },
        )

    def log_index(
        self,
        count: int,
        duration_ms: float,
        *,
        rebuild: bool,
    ) -> None:
        self.log(
            "index",
            {
                "count": count,
                "duration_ms": round(duration_ms, 2),
                "rebuild": rebuild,
            },
        )

    # --- Read-side aggregations -------------------------------------------------

    def fetch_recent(self, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        try:
            with self._conn() as conn:
                if kind:
                    cur = conn.execute(
                        "SELECT ts, kind, payload FROM events WHERE kind = ? "
                        "ORDER BY ts DESC LIMIT ?",
                        (kind, limit),
                    )
                else:
                    cur = conn.execute(
                        "SELECT ts, kind, payload FROM events ORDER BY ts DESC LIMIT ?",
                        (limit,),
                    )
                return [
                    {"ts": ts, "kind": k, "payload": json.loads(p)} for ts, k, p in cur.fetchall()
                ]
        except sqlite3.Error as exc:
            logger.warning("Telemetry read failed: %s", exc)
            return []

    def stats_summary(self) -> dict[str, Any]:
        """Return: total events, per-kind count, top searched skills (loaded),
        top queries, miss rate (searches with top1<0.4)."""
        if not self.db_path.exists():
            return {
                "enabled": self.enabled,
                "db_path": str(self.db_path),
                "exists": False,
                "totals": {},
                "top_loaded": [],
                "top_queries": [],
                "miss_rate": 0.0,
            }
        with self._conn() as conn:
            totals = dict(
                conn.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind").fetchall()
            )

            # Top loaded skills
            top_loaded: dict[str, int] = {}
            for (payload,) in conn.execute(
                "SELECT payload FROM events WHERE kind = 'load'"
            ).fetchall():
                d = json.loads(payload)
                if d.get("found"):
                    name = d.get("skill_name", "?")
                    top_loaded[name] = top_loaded.get(name, 0) + 1

            # Top queries + miss rate
            queries: dict[str, int] = {}
            misses = 0
            total_searches = 0
            for (payload,) in conn.execute(
                "SELECT payload FROM events WHERE kind = 'search'"
            ).fetchall():
                d = json.loads(payload)
                q = (d.get("query") or "").strip().lower()
                if q:
                    queries[q] = queries.get(q, 0) + 1
                total_searches += 1
                if float(d.get("top1_score", 0.0)) < 0.4:
                    misses += 1

        miss_rate = (misses / total_searches) if total_searches else 0.0

        return {
            "enabled": self.enabled,
            "db_path": str(self.db_path),
            "exists": True,
            "totals": totals,
            "top_loaded": sorted(top_loaded.items(), key=lambda x: -x[1])[:10],
            "top_queries": sorted(queries.items(), key=lambda x: -x[1])[:10],
            "miss_rate": miss_rate,
            "total_searches": total_searches,
        }
