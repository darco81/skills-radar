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


class MLXEmbedder:
    """MLX-native embedder for Apple Silicon. Opt-in via [mlx] extras.

    Default model `mlx-community/Qwen3-Embedding-8B-4bit-DWQ` (4096-dim,
    8B params, 4-bit quantized, ~4 GB on disk). Pulls from HF cache if
    present, downloads on first run otherwise. Mac-only - raises
    RuntimeError on non-arm64.
    """

    def __init__(self, model_name: str = "mlx-community/Qwen3-Embedding-8B-4bit-DWQ") -> None:
        import platform

        if platform.machine() != "arm64":
            msg = (
                f"MLX embedder requires Apple Silicon (arm64), got {platform.machine()}. "
                "Use sentence-transformers backend instead."
            )
            raise RuntimeError(msg)

        try:
            from mlx_embeddings import generate, load
        except ImportError as exc:
            msg = "MLX embedder requires the [mlx] extras: `pip install skills-radar[mlx]`."
            raise ImportError(msg) from exc

        logger.info("Loading MLX embedder model: %s", model_name)
        self._model, self._tokenizer = load(model_name)
        self._generate = generate
        self._dim = self._probe_dimension()
        logger.info("MLX embedder ready (%d-dim)", self._dim)

    def _probe_dimension(self) -> int:
        out = self._generate(self._model, self._tokenizer, "probe")
        return int(out.text_embeds.shape[-1])

    def embed(self, text: str) -> list[float]:
        out = self._generate(self._model, self._tokenizer, text)
        return [float(x) for x in out.text_embeds[0].tolist()]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out = self._generate(self._model, self._tokenizer, texts)
        return [[float(x) for x in row] for row in out.text_embeds.tolist()]

    @property
    def dimension(self) -> int:
        return self._dim


def make_embedder(backend: str, model: str) -> EmbedderProtocol:
    """Factory - selects embedder by backend name."""
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    if backend == "mlx":
        return MLXEmbedder(model)
    msg = (
        f"Unsupported embedder backend: {backend!r}. "
        "Use 'sentence-transformers' or 'mlx' (Mac, requires [mlx] extras)."
    )
    raise ValueError(msg)
