"""FAISS-backed skill store. Lighter alternative to ChromaDB.

Use case: minimum dependencies (FAISS is one wheel, ~30 MB), single
directory with two files (`faiss.index` + `meta.json`), no SQLite or
network needed. Good for small corpora (<5k skills) or restrictive
environments.

Same duck-typed interface as ChromaDB-backed `SkillStore`:
upsert / upsert_batch / search / get / delete / count / list_all / reset.

Vector index: FAISS IndexFlatIP with L2-normalized vectors → equivalent
to cosine similarity. Each upsert appends; deletes use a tombstone
mask (FAISS Flat doesn't support delete-in-place efficiently, but our
corpus size makes that fine).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FAISSStore:
    """FAISS IndexFlatIP wrapper with metadata sidecar.

    Persistence: `<path>/faiss.index` + `<path>/meta.json`. On instantiate,
    loads existing index if present; otherwise creates empty.
    """

    def __init__(self, path: Path, dim: int = 384) -> None:
        try:
            import faiss
        except ImportError as exc:
            msg = "FAISS store requires the [faiss] extras: `pip install skills-radar[faiss]`."
            raise ImportError(msg) from exc

        self._faiss = faiss
        self._dim = dim
        self._path = Path(path).expanduser()
        self._path.mkdir(parents=True, exist_ok=True)

        self._index_path = self._path / "faiss.index"
        self._meta_path = self._path / "meta.json"

        self._meta: dict[str, dict[str, Any]] = {}  # name → {metadata, document}
        self._idx_to_name: list[str | None] = []  # FAISS row idx → name (None = tombstoned)
        self._name_to_idx: dict[str, int] = {}

        if self._index_path.exists() and self._meta_path.exists():
            self._load()
        else:
            self._index = faiss.IndexFlatIP(dim)
            self._save()
        logger.info("FAISS store ready at %s (%d skills)", self._path, self.count())

    def _load(self) -> None:
        self._index = self._faiss.read_index(str(self._index_path))
        if self._index.d != self._dim:
            logger.warning(
                "FAISS index has dim=%d but embedder produces %d. Recreating.",
                self._index.d,
                self._dim,
            )
            self._index = self._faiss.IndexFlatIP(self._dim)
            self._meta = {}
            self._idx_to_name = []
            self._name_to_idx = {}
            self._save()
            return
        with self._meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
        self._meta = data.get("meta", {})
        self._idx_to_name = data.get("idx_to_name", [])
        self._name_to_idx = {n: i for i, n in enumerate(self._idx_to_name) if n is not None}

    def _save(self) -> None:
        self._faiss.write_index(self._index, str(self._index_path))
        payload = {"meta": self._meta, "idx_to_name": self._idx_to_name, "dim": self._dim}
        self._meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        """L2-normalize so IndexFlatIP behaves as cosine similarity."""
        import math

        s = math.sqrt(sum(x * x for x in vec))
        if s < 1e-12:
            return list(vec)
        return [x / s for x in vec]

    def upsert(
        self,
        skill_id: str,
        embedding: list[float],
        metadata: dict[str, Any],
        document: str,
    ) -> None:
        import numpy as np

        # If already present → tombstone the old index row (mark None) and append fresh
        if skill_id in self._name_to_idx:
            old_idx = self._name_to_idx.pop(skill_id)
            self._idx_to_name[old_idx] = None

        norm = self._normalize(embedding)
        arr = np.asarray([norm], dtype="float32")
        self._index.add(arr)

        new_idx = self._index.ntotal - 1
        self._idx_to_name.append(skill_id)
        self._name_to_idx[skill_id] = new_idx
        self._meta[skill_id] = {"metadata": metadata, "document": document}
        self._save()

    def upsert_batch(
        self,
        skill_ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        if not skill_ids:
            return
        import numpy as np

        # Tombstone any existing entries
        for sid in skill_ids:
            if sid in self._name_to_idx:
                old_idx = self._name_to_idx.pop(sid)
                self._idx_to_name[old_idx] = None

        normalized = [self._normalize(e) for e in embeddings]
        arr = np.asarray(normalized, dtype="float32")
        starting = self._index.ntotal
        self._index.add(arr)

        for offset, sid in enumerate(skill_ids):
            new_idx = starting + offset
            self._idx_to_name.append(sid)
            self._name_to_idx[sid] = new_idx
            self._meta[sid] = {"metadata": metadatas[offset], "document": documents[offset]}
        self._save()

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,  # noqa: ARG002 - filter not yet supported
    ) -> list[dict[str, Any]]:
        if self.count() == 0:
            return []
        import numpy as np

        q = np.asarray([self._normalize(query_embedding)], dtype="float32")
        # Pull more than top_k to compensate for tombstones
        k = min(top_k * 4, self._index.ntotal)
        scores, indices = self._index.search(q, k)

        out: list[dict[str, Any]] = []
        for score, idx in zip(scores[0].tolist(), indices[0].tolist(), strict=True):
            if idx < 0 or idx >= len(self._idx_to_name):
                continue
            name = self._idx_to_name[idx]
            if name is None:  # tombstoned
                continue
            entry = self._meta.get(name, {})
            distance = max(0.0, 1.0 - float(score))  # IP→similarity; distance = 1 - sim
            out.append(
                {
                    "id": name,
                    "metadata": entry.get("metadata", {}),
                    "document": entry.get("document", ""),
                    "distance": distance,
                }
            )
            if len(out) >= top_k:
                break
        return out

    def get(self, skill_id: str) -> dict[str, Any] | None:
        if skill_id not in self._name_to_idx:
            return None
        entry = self._meta.get(skill_id, {})
        return {
            "id": skill_id,
            "metadata": entry.get("metadata", {}),
            "document": entry.get("document", ""),
        }

    def delete(self, skill_id: str) -> None:
        if skill_id not in self._name_to_idx:
            return
        old_idx = self._name_to_idx.pop(skill_id)
        self._idx_to_name[old_idx] = None
        self._meta.pop(skill_id, None)
        self._save()

    def count(self) -> int:
        return sum(1 for n in self._idx_to_name if n is not None)

    def list_all(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in self._idx_to_name:
            if name is None:
                continue
            entry = self._meta.get(name, {})
            out.append(
                {
                    "id": name,
                    "metadata": entry.get("metadata", {}),
                    "document": entry.get("document", ""),
                }
            )
        return out

    def reset(self) -> None:
        self._index = self._faiss.IndexFlatIP(self._dim)
        self._meta = {}
        self._idx_to_name = []
        self._name_to_idx = {}
        self._save()
        logger.info("FAISS store reset.")
