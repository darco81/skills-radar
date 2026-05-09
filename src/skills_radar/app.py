"""Application context - wires config, embedder, store, BM25, indexer.

Single source of truth for the running server's state. The MCP server and
CLI both consume this; tests construct it with custom config.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from skills_radar.config import Config
from skills_radar.embedder import EmbedderProtocol, make_embedder
from skills_radar.indexer import SkillRecord, find_skill_files, parse_skill_file
from skills_radar.rewriter import QueryRewriter, make_rewriter
from skills_radar.sanitize import TrustTier
from skills_radar.store import SkillStore

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class AppContext:
    """Holds the running services. Constructed once at server startup."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.embedder: EmbedderProtocol = make_embedder(
            self.config.embedder.backend, self.config.embedder.model
        )
        self.store = SkillStore(self.config.store.path)
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[str] = []
        self._rebuild_bm25_from_store()
        self.rewriter: QueryRewriter = self._build_rewriter()

    def _build_rewriter(self) -> QueryRewriter:
        rcfg = self.config.retrieval.rewriter
        if not rcfg.enabled:
            return make_rewriter("none")
        return make_rewriter(
            rcfg.backend,
            url=rcfg.url,
            model=rcfg.model,
            timeout=rcfg.timeout,
        )

    def reindex(self, *, rebuild: bool = False) -> int:
        """Scan paths and (re)index all SKILL.md files. Returns count indexed."""
        if rebuild:
            self.store.reset()

        files = find_skill_files(self.config.paths)
        records: list[SkillRecord] = []
        for f in files:
            rec = parse_skill_file(
                f,
                trusted_paths=self.config.trust.trusted_paths,
                max_size_kb=self.config.sanitization.max_skill_size_kb,
                strip_live_exec=self.config.sanitization.strip_live_exec,
            )
            if rec is None:
                continue
            if rec.disable_model_invocation:
                logger.debug("Skipping model-invocation-disabled: %s", rec.name)
                continue
            records.append(rec)

        records = _dedupe_by_name(records)

        if not records:
            logger.warning("No valid SKILL.md files found in configured paths.")
            self._bm25 = None
            self._bm25_ids = []
            return 0

        ids = [r.name for r in records]
        texts = [r.indexed_text for r in records]
        embeddings = self.embedder.embed_batch(texts)
        metadatas = [_record_to_metadata(r) for r in records]

        self.store.upsert_batch(ids, embeddings, metadatas, texts)
        self._rebuild_bm25_from_store()
        logger.info("Reindexed %d skills", len(records))
        return len(records)

    def _rebuild_bm25_from_store(self) -> None:
        """Rebuild in-memory BM25 corpus from the persistent store."""
        items = self.store.list_all()
        self._bm25_ids = [i["id"] for i in items]
        corpus = [_tokenize(i["document"]) for i in items]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def hybrid_search(
        self,
        query: str,
        top_k: int,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieval - fused semantic + BM25 scores. Returns ranked list."""
        if self.store.count() == 0:
            return []

        rewritten = self.rewriter.rewrite(query)
        query_emb = self.embedder.embed(rewritten)
        # Pull more than top_k from semantic for fusion headroom
        oversample = max(top_k * 4, 20)
        sem_hits = self.store.search(query_emb, top_k=oversample)

        bm25_scores: dict[str, float] = {}
        if self._bm25 is not None:
            raw = self._bm25.get_scores(_tokenize(rewritten))
            bm25_scores = {self._bm25_ids[i]: float(raw[i]) for i in range(len(raw))}
        max_bm25 = max(bm25_scores.values(), default=0.0)
        if max_bm25 < 1e-6:
            max_bm25 = 1.0  # avoid divide-by-zero; lexical signal will be ~0

        w_sem = self.config.retrieval.hybrid_weight_semantic
        w_lex = self.config.retrieval.hybrid_weight_lexical

        fused: list[dict[str, Any]] = []
        for hit in sem_hits:
            sem_score = max(0.0, 1.0 - float(hit["distance"]))  # cosine distance → similarity
            lex_score = bm25_scores.get(hit["id"], 0.0) / max_bm25
            fused.append(
                {
                    "name": hit["id"],
                    "score": w_sem * sem_score + w_lex * lex_score,
                    "metadata": hit["metadata"],
                    "document": hit["document"],
                    "_debug": {"sem": sem_score, "lex": lex_score},
                }
            )

        if tags:
            wanted = {t.strip().lower() for t in tags}
            fused = [
                r
                for r in fused
                if wanted.intersection(_split_tags(r["metadata"].get("hub_tags", "")))
            ]

        fused.sort(key=lambda r: r["score"], reverse=True)
        return fused[:top_k]

    def handle_change_upsert(self, path: Path) -> None:
        """Re-index a single SKILL.md (created/modified). Used by watcher."""
        rec = parse_skill_file(
            path,
            trusted_paths=self.config.trust.trusted_paths,
            max_size_kb=self.config.sanitization.max_skill_size_kb,
            strip_live_exec=self.config.sanitization.strip_live_exec,
        )
        if rec is None:
            logger.debug("Watcher upsert: invalid skill ignored: %s", path)
            return
        if rec.disable_model_invocation:
            logger.debug("Watcher upsert: model-invocation-disabled, skip: %s", rec.name)
            return
        existing = self.store.get(rec.name)
        if existing is not None:
            existing_path = existing.get("metadata", {}).get("path", "")
            if existing_path and existing_path != str(path):
                # Same name from different path - keep higher-priority one
                ex_trust = existing.get("metadata", {}).get("trust", "untrusted")
                if not _candidate_wins(rec.trust.value, ex_trust):
                    logger.debug(
                        "Watcher upsert: lower-priority %s (%s) skipped - kept %s (%s)",
                        rec.name,
                        rec.trust.value,
                        existing_path,
                        ex_trust,
                    )
                    return

        embedding = self.embedder.embed(rec.indexed_text)
        metadata = _record_to_metadata(rec)
        self.store.upsert(rec.name, embedding, metadata, rec.indexed_text)
        self._rebuild_bm25_from_store()
        logger.info("Watcher upsert: %s (%s)", rec.name, path)

    def handle_change_delete(self, path: Path) -> None:
        """Remove a skill whose SKILL.md was deleted or moved away."""
        items = self.store.list_all()
        target = next(
            (i for i in items if (i.get("metadata", {}) or {}).get("path") == str(path)),
            None,
        )
        if target is None:
            logger.debug("Watcher delete: no indexed record for %s", path)
            return
        name = target["id"]
        self.store.delete(name)
        self._rebuild_bm25_from_store()
        logger.info("Watcher delete: %s (%s)", name, path)

    def load_record(self, name: str) -> tuple[SkillRecord | None, dict[str, Any] | None]:
        """Re-parse SKILL.md fresh from disk. Avoids stale-cache bugs."""
        stored = self.store.get(name)
        if stored is None:
            return None, None
        path = Path(stored["metadata"].get("path", ""))
        if not path.exists():
            logger.warning("Indexed skill %r path missing: %s", name, path)
            return None, stored["metadata"]
        record = parse_skill_file(
            path,
            trusted_paths=self.config.trust.trusted_paths,
            max_size_kb=self.config.sanitization.max_skill_size_kb,
            strip_live_exec=self.config.sanitization.strip_live_exec,
        )
        return record, stored["metadata"]


def _record_to_metadata(r: SkillRecord) -> dict[str, Any]:
    return {
        "description": r.description,
        "when_to_use": r.when_to_use,
        "hub_tags": r.hub_tags,
        "trust": r.trust.value if isinstance(r.trust, TrustTier) else str(r.trust),
        "path": r.path,
        "scope": r.scope,
        "bundled_files": r.bundled_files,
        "disable_invoke": r.disable_model_invocation,
        "warnings": r.warnings,
    }


def _split_tags(s: str) -> set[str]:
    if not s:
        return set()
    return {t.strip().lower() for t in s.split(",") if t.strip()}


_TIER_PRIORITY = {
    "trusted": 0,
    "user": 1,
    "verified": 2,
    "untrusted": 3,
}


def _dedupe_by_name(records: list[SkillRecord]) -> list[SkillRecord]:
    """Resolve same-name collisions across scan paths.

    Priority (lowest wins): trusted → user → verified → untrusted.
    Within the same tier: latest mtime wins. Plugin caches with multiple
    versions (e.g. superpowers/5.0.6 and 5.1.0) collapse to one entry.
    """
    by_name: dict[str, SkillRecord] = {}
    for rec in records:
        existing = by_name.get(rec.name)
        if existing is None:
            by_name[rec.name] = rec
            continue
        if _is_higher_priority(rec, existing):
            logger.debug(
                "Dedup: %r - %s (%s) supersedes %s (%s)",
                rec.name,
                rec.path,
                rec.trust.value,
                existing.path,
                existing.trust.value,
            )
            by_name[rec.name] = rec
    return list(by_name.values())


def _is_higher_priority(candidate: SkillRecord, existing: SkillRecord) -> bool:
    cand_tier = _TIER_PRIORITY.get(candidate.trust.value, 99)
    exist_tier = _TIER_PRIORITY.get(existing.trust.value, 99)
    if cand_tier != exist_tier:
        return cand_tier < exist_tier
    try:
        return Path(candidate.path).stat().st_mtime > Path(existing.path).stat().st_mtime
    except OSError:
        return False


def _candidate_wins(candidate_trust: str, existing_trust: str) -> bool:
    """Pure-string version of _is_higher_priority for the watcher path,
    where we have trust strings from store metadata, not full records.
    """
    cand_tier = _TIER_PRIORITY.get(candidate_trust, 99)
    exist_tier = _TIER_PRIORITY.get(existing_trust, 99)
    return cand_tier < exist_tier
