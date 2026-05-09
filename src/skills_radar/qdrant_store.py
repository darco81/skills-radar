"""Qdrant-backed skill store. Opt-in via [qdrant] extras.

Production-grade vector DB. Use case: scaling to 100k+ skills, or
reusing an existing Qdrant instance (e.g., the one already powering
sdet-brain). Default skills-radar still uses ChromaDB; this is a
swappable backend selected by config `store.backend: qdrant`.

Same duck-typed interface as ChromaDB-backed `SkillStore`:
upsert / upsert_batch / search / get / delete / count / list_all / reset.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:6333"
DEFAULT_COLLECTION = "skills_v1"
QDRANT_NAMESPACE = uuid.UUID("6f3c9f6a-7f8e-4f80-9a0a-2b2b7c9b0e10")


class QdrantStore:
    """Wrapper around qdrant-client. Uses one collection, cosine distance.

    Skill IDs are strings (skill names). Qdrant requires int or UUID
    point IDs, so we derive a deterministic UUID5 from the skill name
    using a project-specific namespace. The original skill name is
    preserved in the payload as `_name` for retrieval.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        collection: str = DEFAULT_COLLECTION,
        dim: int = 384,
    ) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
        except ImportError as exc:
            msg = "Qdrant store requires the [qdrant] extras: `pip install skills-radar[qdrant]`."
            raise ImportError(msg) from exc

        self._client = QdrantClient(url=url)
        self._collection = collection
        self._dim = dim
        self._VectorParams = VectorParams
        self._Distance = Distance

        self._ensure_collection()
        logger.info(
            "Qdrant store ready at %s collection=%s (%d skills)",
            url,
            collection,
            self.count(),
        )

    def _ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            info = self._client.get_collection(self._collection)
            current_dim = info.config.params.vectors.size
            if current_dim != self._dim:
                logger.warning(
                    "Qdrant collection %s exists with dim=%d but embedder produces dim=%d. "
                    "Recreating collection.",
                    self._collection,
                    current_dim,
                    self._dim,
                )
                self._client.delete_collection(self._collection)
                existing.discard(self._collection)
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=self._VectorParams(size=self._dim, distance=self._Distance.COSINE),
            )

    @staticmethod
    def _point_id(skill_name: str) -> str:
        return str(uuid.uuid5(QDRANT_NAMESPACE, skill_name))

    def upsert(
        self,
        skill_id: str,
        embedding: list[float],
        metadata: dict[str, Any],
        document: str,
    ) -> None:
        from qdrant_client.models import PointStruct

        payload = {**_clean_payload(metadata), "_name": skill_id, "_document": document}
        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(
                    id=self._point_id(skill_id),
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

    def upsert_batch(
        self,
        skill_ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        if not skill_ids:
            return
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=self._point_id(skill_ids[i]),
                vector=embeddings[i],
                payload={
                    **_clean_payload(metadatas[i]),
                    "_name": skill_ids[i],
                    "_document": documents[i],
                },
            )
            for i in range(len(skill_ids))
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,  # noqa: ARG002 - filter not yet wired
    ) -> list[dict[str, Any]]:
        if self.count() == 0:
            return []
        results = self._client.query_points(
            collection_name=self._collection,
            query=query_embedding,
            limit=top_k,
            with_payload=True,
        ).points

        out: list[dict[str, Any]] = []
        for hit in results:
            payload = hit.payload or {}
            name = payload.pop("_name", str(hit.id))
            document = payload.pop("_document", "")
            distance = 1.0 - float(hit.score)  # cosine similarity → distance
            out.append(
                {
                    "id": name,
                    "metadata": payload,
                    "document": document,
                    "distance": distance,
                }
            )
        return out

    def get(self, skill_id: str) -> dict[str, Any] | None:
        results = self._client.retrieve(
            collection_name=self._collection,
            ids=[self._point_id(skill_id)],
            with_payload=True,
        )
        if not results:
            return None
        payload = results[0].payload or {}
        name = payload.pop("_name", skill_id)
        document = payload.pop("_document", "")
        return {"id": name, "metadata": payload, "document": document}

    def delete(self, skill_id: str) -> None:
        from qdrant_client.models import PointIdsList

        self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=[self._point_id(skill_id)]),
        )

    def count(self) -> int:
        return self._client.count(collection_name=self._collection, exact=True).count

    def list_all(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                name = payload.pop("_name", str(p.id))
                document = payload.pop("_document", "")
                out.append({"id": name, "metadata": payload, "document": document})
            if offset is None:
                break
        return out

    def reset(self) -> None:
        self._client.delete_collection(self._collection)
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=self._VectorParams(size=self._dim, distance=self._Distance.COSINE),
        )
        logger.info("Qdrant collection %s reset.", self._collection)


def _clean_payload(meta: dict[str, Any]) -> dict[str, Any]:
    """Qdrant payload accepts richer types than ChromaDB. Keep lists/dicts as-is."""
    cleaned: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        cleaned[k] = v
    return cleaned
