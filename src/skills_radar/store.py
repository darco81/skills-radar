"""ChromaDB-backed skill store.

Persists embeddings + metadata + indexed text.
Body of SKILL.md is stored on disk separately (we keep only path in metadata).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "skills_v1"


class SkillStore:
    """Wrapper around ChromaDB persistent client + a single collection."""

    def __init__(self, path: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        path = Path(path).expanduser()
        path.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=str(path),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Store ready at %s (%d skills)", path, self.count())

    def upsert(
        self,
        skill_id: str,
        embedding: list[float],
        metadata: dict[str, Any],
        document: str,
    ) -> None:
        """Insert or update a single skill."""
        self._collection.upsert(
            ids=[skill_id],
            embeddings=[embedding],
            metadatas=[_clean_metadata(metadata)],
            documents=[document],
        )

    def upsert_batch(
        self,
        skill_ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        """Batch upsert."""
        if not skill_ids:
            return
        self._collection.upsert(
            ids=skill_ids,
            embeddings=embeddings,
            metadatas=[_clean_metadata(m) for m in metadatas],
            documents=documents,
        )

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search. Returns list of {id, metadata, document, distance}."""
        if self.count() == 0:
            return []
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.count()),
            where=where,
        )
        ids = results["ids"][0]
        metadatas = results["metadatas"][0]
        documents = results["documents"][0]
        distances = results["distances"][0]
        return [
            {
                "id": ids[i],
                "metadata": metadatas[i],
                "document": documents[i],
                "distance": distances[i],
            }
            for i in range(len(ids))
        ]

    def get(self, skill_id: str) -> dict[str, Any] | None:
        """Fetch a single skill by id."""
        result = self._collection.get(ids=[skill_id])
        if not result["ids"]:
            return None
        return {
            "id": result["ids"][0],
            "metadata": result["metadatas"][0],
            "document": result["documents"][0],
        }

    def delete(self, skill_id: str) -> None:
        """Remove a single skill."""
        self._collection.delete(ids=[skill_id])

    def count(self) -> int:
        return self._collection.count()

    def list_all(self) -> list[dict[str, Any]]:
        """Return all skills (id + metadata + document). For BM25 corpus build + listing."""
        result = self._collection.get()
        ids = result["ids"]
        metadatas = result["metadatas"]
        documents = result["documents"]
        return [
            {"id": ids[i], "metadata": metadatas[i], "document": documents[i]}
            for i in range(len(ids))
        ]

    def reset(self) -> None:
        """Drop everything. Used for --rebuild."""
        self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Store reset.")


def _clean_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """ChromaDB only accepts str/int/float/bool in metadata. Coerce lists to comma-strings."""
    cleaned: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        elif isinstance(v, list):
            cleaned[k] = ",".join(str(x) for x in v)
        else:
            cleaned[k] = str(v)
    return cleaned
