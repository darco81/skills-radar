"""Tests for the optional reranker (NoOp + Ollama)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from skills_radar.reranker import (
    NoOpReranker,
    OllamaReranker,
    make_reranker,
)


def test_noop_passthrough():
    r = NoOpReranker()
    cands = [{"name": "a", "score": 0.5}, {"name": "b", "score": 0.3}]
    assert r.rerank("query", cands) == cands


def test_factory_default():
    assert isinstance(make_reranker("none"), NoOpReranker)


def test_factory_ollama():
    r = make_reranker("ollama", url="http://x:1", model="m", timeout=1.0)
    assert isinstance(r, OllamaReranker)


def test_factory_mlx_returns_real_implementation():
    """MLX reranker is now implemented (was placeholder until v0.3.0a1)."""
    import platform

    if platform.machine() != "arm64":
        with pytest.raises(RuntimeError, match="Apple Silicon"):
            make_reranker("mlx")
        return
    from skills_radar.reranker import MLXReranker

    r = make_reranker("mlx")
    assert isinstance(r, MLXReranker)
    # Lazy load: model not loaded yet on construction
    assert r._loaded is False


def test_factory_unknown():
    with pytest.raises(ValueError, match="Unknown reranker"):
        make_reranker("voodoo")


def test_ollama_url_validation():
    with pytest.raises(ValueError, match="http"):
        OllamaReranker(url="file:///tmp/evil")


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_ollama_rerank_orders_by_score():
    r = OllamaReranker()
    cands = [
        {"name": "a", "score": 0.5, "metadata": {"description": "low relevance"}},
        {"name": "b", "score": 0.3, "metadata": {"description": "high relevance"}},
        {"name": "c", "score": 0.4, "metadata": {"description": "medium"}},
    ]
    # mock returns: a→2, b→9, c→5  (b should win)
    responses = iter(["2", "9", "5"])
    with patch(
        "urllib.request.urlopen",
        side_effect=lambda *a, **k: _FakeResp(json.dumps({"response": next(responses)})),
    ):
        out = r.rerank("relevance test", cands)
    assert out[0]["name"] == "b"
    assert out[1]["name"] == "c"
    assert out[2]["name"] == "a"
    assert out[0]["_rerank_score"] == 9.0


def test_ollama_rerank_falls_back_on_network_error():
    r = OllamaReranker(timeout=0.1)
    cands = [{"name": "a", "score": 0.5, "metadata": {"description": "x"}}]
    with patch("urllib.request.urlopen", side_effect=TimeoutError("boom")):
        out = r.rerank("q", cands)
    assert out == cands


def test_ollama_rerank_handles_no_integer_in_response():
    r = OllamaReranker()
    cands = [
        {"name": "a", "score": 0.5, "metadata": {"description": "x"}},
        {"name": "b", "score": 0.3, "metadata": {"description": "y"}},
    ]
    with patch(
        "urllib.request.urlopen", return_value=_FakeResp(json.dumps({"response": "no number here"}))
    ):
        out = r.rerank("q", cands)
    # Both default to 5.0 - order preserved, but rerank scores set
    assert all(c["_rerank_score"] == 5.0 for c in out)


def test_ollama_rerank_empty_candidates():
    r = OllamaReranker()
    assert r.rerank("q", []) == []


def test_ollama_rerank_scores_full_indexed_text_including_when_to_use():
    """Reranker must score the full `document` (description + when_to_use),
    consistent with what the embedder and BM25 index. Regression: it scored
    metadata.description only, so trigger phrases living in when_to_use were
    invisible to the reranker even though they drive retrieval."""
    r = OllamaReranker()
    cands = [
        {
            "name": "perf-vue-runtime",
            "score": 0.5,
            "metadata": {"description": "Audit Vue runtime performance."},
            # document = indexed_text = description + "\n\n" + when_to_use
            "document": (
                "Audit Vue runtime performance.\n\n"
                "Triggers: 'watcher leak', 'INP regression', 'shallowRef'."
            ),
        },
    ]
    captured: list[str] = []

    def _capture(req, *_a, **_k):
        captured.append(req.data.decode("utf-8"))
        return _FakeResp(json.dumps({"response": "8"}))

    # Query is deliberately disjoint from the when_to_use phrases, so the
    # only way "shallowRef" can appear in the scorer prompt is via `document`.
    with patch("urllib.request.urlopen", side_effect=_capture):
        r.rerank("my vue app feels janky", cands)

    assert "shallowRef" in captured[0]
