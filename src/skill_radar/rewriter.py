"""Query rewriter - optional pre-embedding step.

Takes the user's raw query (often vague, multi-language, or laden with
filler words) and rewrites it into a richer English-keyword form better
suited to embedding similarity. Off by default - opt in via config.

Backends:
- `none` - passthrough, no rewriting (default)
- `ollama` - local Ollama instance (no API key, free, fast on M-series)

Adding new backends (Voyage, OpenAI, etc.) is a matter of subclassing
QueryRewriter and registering in make_rewriter().
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


def _clean(text: str) -> str:
    """Strip wrapping quotes / trailing punctuation that LLMs sometimes add."""
    text = text.strip().strip("\"'`")
    if "\n" in text:
        text = text.split("\n", 1)[0]
    return text.rstrip(".,;:!?")


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
    msg = f"Unknown query rewriter backend: {backend!r}"
    raise ValueError(msg)
