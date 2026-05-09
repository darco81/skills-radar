"""Optional cross-encoder reranker over hybrid_search top-k.

Off by default. Opt in via config.retrieval.reranker.enabled.

Backends:
- `none`     - passthrough (default)
- `ollama`   - local LLM scores 0-10 per (query, description) pair
- `mlx`      - placeholder for native MLX reranker (F5+ backlog)

Pattern: hybrid retrieval pulls a wider candidate set (top-20 by default
when reranker is on), reranker scores each, top-N is returned. Adds
500ms-3s of latency per query depending on backend / model size - only
worth it for fuzzy or multilingual queries where the small embedder
struggles.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from typing import Any, Protocol

logger = logging.getLogger(__name__)

OVERSAMPLE_WHEN_ENABLED = 20  # candidate pool size before reranking

RERANK_SYSTEM_PROMPT = (
    "You are a relevance scorer for a skill discovery system. "
    "Given a user query and a candidate skill description, output a "
    "single integer 0-10 representing how well the skill matches the "
    "query. 0=irrelevant, 5=tangentially related, 10=perfect match. "
    "Output ONLY the integer, nothing else - no explanation, no quotes, "
    "no decimal."
)

_INTEGER_RE = re.compile(r"\b(10|[0-9])\b")


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class NoOpReranker:
    """Passthrough - returns candidates unchanged."""

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return candidates


class OllamaReranker:
    """Calls a local Ollama instance for per-candidate relevance scoring.

    Robust to errors: any HTTP failure / timeout / bad parse falls back
    to the original ranking (NoOp behavior). Reranker must never break
    a search.
    """

    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "gemma4:e4b",
        timeout: float = 8.0,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            msg = f"Reranker URL must use http(s) scheme, got: {url!r}"
            raise ValueError(msg)
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _score_one(self, query: str, description: str) -> float:
        prompt = f"Query: {query}\n\nSkill description: {description}\n\nScore 0-10:"
        payload = {
            "model": self.model,
            "system": RERANK_SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 4},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 - scheme validated in __init__
            f"{self.url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        text = (json.loads(body).get("response") or "").strip()
        m = _INTEGER_RE.search(text)
        if not m:
            logger.debug("Reranker: no integer in response %r - returning 5", text)
            return 5.0
        return float(m.group(1))

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return candidates
        try:
            t0 = time.perf_counter()
            scored: list[tuple[float, dict[str, Any]]] = []
            for cand in candidates:
                desc = (cand.get("metadata") or {}).get("description", "") or cand.get(
                    "document", ""
                )
                score = self._score_one(query, desc[:500])
                scored.append((score, cand))
            scored.sort(key=lambda x: x[0], reverse=True)
            elapsed = (time.perf_counter() - t0) * 1000.0
            logger.info("Reranker scored %d candidates in %.0fms", len(candidates), elapsed)
            return [{**c, "score": float(s) / 10.0, "_rerank_score": float(s)} for s, c in scored]
        except (TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Reranker failed (%s) - returning original ranking", exc)
            return candidates


def make_reranker(backend: str, **kwargs: object) -> Reranker:
    """Factory."""
    backend = (backend or "none").lower()
    if backend == "none":
        return NoOpReranker()
    if backend == "ollama":
        return OllamaReranker(
            url=str(kwargs.get("url", "http://localhost:11434")),
            model=str(kwargs.get("model", "gemma4:e4b")),
            timeout=float(kwargs.get("timeout", 8.0)),  # type: ignore[arg-type]
        )
    if backend == "mlx":
        msg = (
            "MLX-native reranker is on the roadmap but not implemented yet. "
            "Use 'ollama' backend with a local model for now."
        )
        raise NotImplementedError(msg)
    msg = f"Unknown reranker backend: {backend!r}"
    raise ValueError(msg)
