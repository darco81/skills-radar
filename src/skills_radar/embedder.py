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


class OpenAIEmbedder:
    """OpenAI cloud embedder. BYOK via OPENAI_API_KEY env var.

    Default model `text-embedding-3-small` (1536-dim, ~$0.02 per 1M
    tokens - for a 60-skill corpus indexed once that's <$0.01). Use
    `text-embedding-3-large` (3072-dim) for higher quality at ~6×
    the cost.

    Network call per batch - slower than local backends, but no GPU
    needed and quality is excellent across many languages.
    """

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        api_key: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = (
                "OpenAI embedder requires the [openai] extras: `pip install skills-radar[openai]`."
            )
            raise ImportError(msg) from exc

        import os

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            msg = (
                "OPENAI_API_KEY environment variable not set. "
                "Set it or pass api_key= to OpenAIEmbedder."
            )
            raise ValueError(msg)

        self._client = OpenAI(api_key=key)
        self._model = model_name
        # Probe dimension once
        self._dim = self._probe_dimension()
        logger.info("OpenAI embedder ready (%d-dim, model=%s)", self._dim, model_name)

    def _probe_dimension(self) -> int:
        out = self._client.embeddings.create(model=self._model, input="probe")
        return len(out.data[0].embedding)

    def embed(self, text: str) -> list[float]:
        out = self._client.embeddings.create(model=self._model, input=text)
        return list(out.data[0].embedding)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out = self._client.embeddings.create(model=self._model, input=texts)
        return [list(item.embedding) for item in out.data]

    @property
    def dimension(self) -> int:
        return self._dim


class VoyageEmbedder:
    """Voyage AI cloud embedder. BYOK via VOYAGE_API_KEY env var.

    Default model `voyage-3-lite` (512-dim, fast/cheap) - best
    cost/quality tradeoff among hosted embedders for short technical
    text. Use `voyage-3` (1024-dim) for higher quality.

    Specialized for retrieval - outperforms OpenAI text-embedding-3
    on most public benchmarks. Pricing: voyage-3-lite ~$0.02 / 1M
    tokens; voyage-3 ~$0.06 / 1M.
    """

    def __init__(
        self,
        model_name: str = "voyage-3-lite",
        api_key: str | None = None,
    ) -> None:
        try:
            import voyageai
        except ImportError as exc:
            msg = (
                "Voyage embedder requires the [voyage] extras: `pip install skills-radar[voyage]`."
            )
            raise ImportError(msg) from exc

        import os

        key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not key:
            msg = (
                "VOYAGE_API_KEY environment variable not set. "
                "Set it or pass api_key= to VoyageEmbedder."
            )
            raise ValueError(msg)

        self._client = voyageai.Client(api_key=key)
        self._model = model_name
        self._dim = self._probe_dimension()
        logger.info("Voyage embedder ready (%d-dim, model=%s)", self._dim, model_name)

    def _probe_dimension(self) -> int:
        out = self._client.embed(["probe"], model=self._model, input_type="document")
        return len(out.embeddings[0])

    def embed(self, text: str) -> list[float]:
        out = self._client.embed([text], model=self._model, input_type="query")
        return list(out.embeddings[0])

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out = self._client.embed(texts, model=self._model, input_type="document")
        return [list(e) for e in out.embeddings]

    @property
    def dimension(self) -> int:
        return self._dim


def make_embedder(backend: str, model: str) -> EmbedderProtocol:
    """Factory - selects embedder by backend name."""
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    if backend == "mlx":
        return MLXEmbedder(model)
    if backend == "openai":
        return OpenAIEmbedder(model_name=model)
    if backend == "voyage":
        return VoyageEmbedder(model_name=model)
    msg = (
        f"Unsupported embedder backend: {backend!r}. Use 'sentence-transformers', "
        "'mlx' (Mac, [mlx] extras), 'openai' ([openai] extras + OPENAI_API_KEY), "
        "or 'voyage' ([voyage] extras + VOYAGE_API_KEY)."
    )
    raise ValueError(msg)
