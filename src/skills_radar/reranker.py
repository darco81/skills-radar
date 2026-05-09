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


class MLXReranker:
    """MLX-native reranker for Apple Silicon. Opt-in via [mlx] extras.

    100% local - no network, no cloud, no Ollama. Single-pass batch
    scoring: one prompt enumerates all candidates, model returns lines
    of `N=<score>` which are parsed back. ~5-15s per rerank call (one
    inference for the whole top-20 instead of 20 separate calls).

    Mac-only. Falls back to passthrough on any error.

    Default model: same as MLXRewriter - Qwen3-Coder-30B-A3B-Instruct-4bit.
    """

    _SYSTEM_PROMPT = (
        "You score candidate skills for relevance to a user query. "
        "Output ONLY one line per candidate in the form `N=score` "
        "where N is the candidate number (1-indexed) and score is an "
        "integer 0-10 (0=irrelevant, 5=tangentially related, 10=perfect). "
        "No explanation, no commentary, no extra lines. "
        "Example: `1=8\\n2=3\\n3=9`"
    )

    _LINE_RE = re.compile(r"^\s*(\d+)\s*=\s*(\d+)\s*$", re.MULTILINE)

    def __init__(
        self,
        model_name: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
        max_tokens: int = 200,
    ) -> None:
        import platform

        if platform.machine() != "arm64":
            msg = (
                f"MLX reranker requires Apple Silicon (arm64), got {platform.machine()}. "
                "Use the 'ollama' backend instead."
            )
            raise RuntimeError(msg)

        self._model_name = model_name
        self._max_tokens = max_tokens
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from mlx_lm import generate, load
        except ImportError as exc:
            msg = "MLX reranker requires the [mlx] extras: `pip install skills-radar[mlx]`."
            raise ImportError(msg) from exc

        logger.info("Loading MLX reranker model: %s", self._model_name)
        self._model, self._tokenizer = load(self._model_name)
        self._generate = generate
        self._loaded = True

    def _build_prompt(self, query: str, candidates: list[dict[str, Any]]) -> Any:  # noqa: ANN401 - tokenizer.apply_chat_template return type
        lines = [f"Query: {query}", "", "Candidates:"]
        for i, cand in enumerate(candidates, start=1):
            desc = (cand.get("metadata") or {}).get("description", "") or cand.get("document", "")
            desc_clip = desc[:240].replace("\n", " ")
            lines.append(f"{i}. {desc_clip}")
        lines.append("")
        lines.append("Score each (0-10):")
        user_msg = "\n".join(lines)

        return self._tokenizer.apply_chat_template(
            [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            add_generation_prompt=True,
        )

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return candidates
        try:
            self._ensure_loaded()
            t0 = time.perf_counter()
            prompt = self._build_prompt(query, candidates)
            raw = self._generate(
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=max(self._max_tokens, 8 * len(candidates)),
                verbose=False,
            )
            scores = self._parse_scores(raw, len(candidates))
            scored = [(scores.get(i + 1, 5.0), cand) for i, cand in enumerate(candidates)]
            scored.sort(key=lambda x: x[0], reverse=True)
            elapsed = (time.perf_counter() - t0) * 1000.0
            logger.info(
                "MLXReranker scored %d candidates in %.0fms (single pass)",
                len(candidates),
                elapsed,
            )
            return [{**c, "score": float(s) / 10.0, "_rerank_score": float(s)} for s, c in scored]
        except Exception as exc:  # noqa: BLE001 - fallback to original ranking
            logger.warning("MLXReranker failed (%s) - original ranking", exc)
            return candidates

    def _parse_scores(self, text: str, expected: int) -> dict[int, float]:
        out: dict[int, float] = {}
        for match in self._LINE_RE.finditer(text):
            idx = int(match.group(1))
            score = max(0.0, min(10.0, float(match.group(2))))
            out[idx] = score
        if len(out) < expected:
            logger.debug(
                "MLXReranker: parsed %d/%d scores from %r",
                len(out),
                expected,
                text[:200],
            )
        return out


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
        return MLXReranker(
            model_name=str(kwargs.get("model", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit")),
            max_tokens=int(kwargs.get("max_tokens", 200)),  # type: ignore[arg-type]
        )
    msg = f"Unknown reranker backend: {backend!r}"
    raise ValueError(msg)
