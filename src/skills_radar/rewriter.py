"""Query rewriter - optional pre-embedding step.

Takes the user's raw query (often vague, multi-language, or laden with
filler words) and rewrites it into a richer English-keyword form better
suited to embedding similarity. Off by default - opt in via config.

Backends:
- `none`   - passthrough, no rewriting (default)
- `mlx`    - Apple Silicon native, 100% local (no network, no Ollama).
             Recommended for Mac users running the MLX embedder stack.
- `ollama` - local Ollama instance (cross-platform: Linux / Windows /
             Mac without MLX). Resilient HTTP fallback.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Protocol

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = (
    "You rewrite ambiguous user queries into concise English keyword phrases "
    "optimized for semantic search over short technical descriptions. "
    "Do NOT answer the query, do NOT add explanations, do NOT use full "
    "sentences. Output 4-8 keywords separated by spaces, no punctuation, "
    "no quotes. Preserve technical terms verbatim."
)


class QueryRewriter(Protocol):
    """Rewriter interface."""

    def rewrite(self, query: str) -> str: ...


class NoOpRewriter:
    """Passthrough - returns the query unchanged."""

    def rewrite(self, query: str) -> str:
        return query


class OllamaRewriter:
    """Calls a local Ollama instance to rewrite queries.

    Resilient by design: any HTTP error / timeout / parse error falls back
    to returning the original query. Rewriting must never block or break
    a search.
    """

    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "gemma4:e4b",
        timeout: float = 5.0,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            msg = f"Rewriter URL must use http:// or https:// scheme, got: {url!r}"
            raise ValueError(msg)
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def rewrite(self, query: str) -> str:
        try:
            payload = {
                "model": self.model,
                "system": REWRITE_SYSTEM_PROMPT,
                "prompt": query,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 60,
                },
            }
            data = json.dumps(payload).encode("utf-8")
            # Scheme is validated to be http/https in __init__; safe to ignore S310.
            req = urllib.request.Request(  # noqa: S310
                f"{self.url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
            parsed = json.loads(body)
            rewritten = (parsed.get("response") or "").strip()
            if not rewritten:
                logger.debug("OllamaRewriter: empty response, falling back to original")
                return query
            cleaned = _clean(rewritten)
            if cleaned == query:
                return query
            logger.debug("OllamaRewriter: %r → %r", query, cleaned)
            return cleaned
        except (TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("OllamaRewriter failed (%s) - using raw query", exc)
            return query


class MLXRewriter:
    """MLX-native rewriter for Apple Silicon. 100% local, no network.

    Lazily loads a small instruct model on first call. LRU-cached per
    query so repeated identical queries cost only one inference.

    Tradeoff: ~3-7s on first cold query (model load + inference),
    ~1-3s on warm queries. Default model is Qwen3-Coder-30B-A3B-Instruct-4bit
    - MoE with 3B active parameters per token, no thinking-mode preamble.
    Mac-only - raises RuntimeError on non-arm64 with hint to use Ollama.
    """

    _SYSTEM_PROMPT = (
        "Output ONLY 4-8 English keywords (separated by spaces) capturing "
        "the user query intent for semantic search over short technical "
        "skill descriptions. No punctuation, no quotes, no explanation. "
        "Just keywords."
    )

    def __init__(
        self,
        model_name: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
        max_tokens: int = 20,
        cache_size: int = 256,
    ) -> None:
        import platform

        if platform.machine() != "arm64":
            msg = (
                f"MLX rewriter requires Apple Silicon (arm64), got {platform.machine()}. "
                "Use the 'ollama' backend instead."
            )
            raise RuntimeError(msg)

        self._model_name = model_name
        self._max_tokens = max_tokens
        self._cache_size = cache_size
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from mlx_lm import generate, load
        except ImportError as exc:
            msg = "MLX rewriter requires the [mlx] extras: `pip install skills-radar[mlx]`."
            raise ImportError(msg) from exc

        logger.info("Loading MLX rewriter model: %s", self._model_name)
        self._model, self._tokenizer = load(self._model_name)
        self._generate = generate
        self._loaded = True

    def rewrite(self, query: str) -> str:
        cached = self._cache.get(query)
        if cached is not None:
            return cached
        try:
            self._ensure_loaded()
            prompt = self._tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                add_generation_prompt=True,
            )
            raw = self._generate(
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=self._max_tokens,
                verbose=False,
            )
            cleaned = _clean(raw)
            if not cleaned or cleaned == query:
                return query
            cleaned = _dedupe_trailing(cleaned)
            if len(self._cache) >= self._cache_size:
                self._cache.pop(next(iter(self._cache)), None)
            self._cache[query] = cleaned
            logger.debug("MLXRewriter: %r → %r", query, cleaned)
            return cleaned
        except Exception as exc:  # noqa: BLE001 - broad fallback by design
            logger.warning("MLXRewriter failed (%s) - using raw query", exc)
            return query


def _clean(text: str) -> str:
    """Strip wrapping quotes / trailing punctuation that LLMs sometimes add."""
    text = text.strip().strip("\"'`")
    if "\n" in text:
        text = text.split("\n", 1)[0]
    return text.rstrip(".,;:!?")


def _dedupe_trailing(text: str) -> str:
    """Small instruct models often repeat the same keyword 3-5x. Trim to
    the first 8 unique whitespace-separated tokens, preserving order."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for tok in text.split():
        lo = tok.lower()
        if lo in seen_set:
            continue
        seen_set.add(lo)
        seen.append(tok)
        if len(seen) >= 8:
            break
    return " ".join(seen)


def make_rewriter(backend: str, **kwargs: object) -> QueryRewriter:
    """Factory."""
    backend = (backend or "none").lower()
    if backend == "none":
        return NoOpRewriter()
    if backend == "ollama":
        return OllamaRewriter(
            url=str(kwargs.get("url", "http://localhost:11434")),
            model=str(kwargs.get("model", "gemma4:e4b")),
            timeout=float(kwargs.get("timeout", 5.0)),  # type: ignore[arg-type]
        )
    if backend == "mlx":
        return MLXRewriter(
            model_name=str(kwargs.get("model", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit")),
            max_tokens=int(kwargs.get("max_tokens", 20)),  # type: ignore[arg-type]
        )
    msg = f"Unknown query rewriter backend: {backend!r}"
    raise ValueError(msg)
