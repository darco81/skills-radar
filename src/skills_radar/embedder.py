"""Text embedder - sentence-transformers default, swappable."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbedderProtocol(Protocol):
    """Embedder interface - any backend must satisfy this."""

    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...


class SentenceTransformerEmbedder:
    """Default embedder. CPU-fast, cross-platform.

    `all-MiniLM-L6-v2` produces 384-dim vectors. ~90MB model.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedder model: %s", model_name)
        self._model = SentenceTransformer(model_name)
        self._dim = int(self._model.get_sentence_embedding_dimension())
        logger.info("Embedder ready (%d-dim)", self._dim)

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(text, convert_to_numpy=True, show_progress_bar=False)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._model.encode(
            texts, convert_to_numpy=True, show_progress_bar=False, batch_size=32
        )
        return vecs.tolist()

    @property
    def dimension(self) -> int:
        return self._dim


def make_embedder(backend: str, model: str) -> EmbedderProtocol:
    """Factory - selects embedder by backend name."""
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    msg = f"Unsupported embedder backend: {backend!r}. Use 'sentence-transformers'."
    raise ValueError(msg)
