"""Tests for the optional query rewriter (NoOp + Ollama)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from skills_radar.rewriter import (
    NoOpRewriter,
    OllamaRewriter,
    _clean,
    make_rewriter,
)


def test_noop_passthrough():
    r = NoOpRewriter()
    assert r.rewrite("WCAG audit") == "WCAG audit"
    assert r.rewrite("") == ""


def test_factory_default_is_noop():
    r = make_rewriter("none")
    assert isinstance(r, NoOpRewriter)


def test_factory_ollama():
    r = make_rewriter("ollama", url="http://x:1", model="m", timeout=1.0)
    assert isinstance(r, OllamaRewriter)
    assert r.url == "http://x:1"
    assert r.model == "m"
    assert r.timeout == 1.0


def test_factory_unknown_raises():
    with pytest.raises(ValueError, match="Unknown query rewriter"):
        make_rewriter("magic")


def test_clean_strips_quotes_and_punct():
    assert _clean('"foo bar"') == "foo bar"
    assert _clean("foo bar.") == "foo bar"
    assert _clean("foo\nbar baz") == "foo"
    assert _clean("`hello`") == "hello"


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_rewrite_success():
    r = OllamaRewriter(model="gemma4:e4b")
    body = json.dumps({"response": "wcag accessibility audit"})
    with patch("urllib.request.urlopen", return_value=_FakeResp(body)):
        out = r.rewrite("audyt dostępności WCAG")
    assert out == "wcag accessibility audit"


def test_ollama_rewrite_empty_response_falls_back():
    r = OllamaRewriter()
    body = json.dumps({"response": "   "})
    with patch("urllib.request.urlopen", return_value=_FakeResp(body)):
        out = r.rewrite("Vue memory leak")
    assert out == "Vue memory leak"


def test_ollama_rewrite_network_error_falls_back():
    r = OllamaRewriter(timeout=0.1)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("boom")):
        out = r.rewrite("LinkedIn post")
    assert out == "LinkedIn post"


def test_ollama_rewrite_invalid_json_falls_back():
    r = OllamaRewriter()
    with patch("urllib.request.urlopen", return_value=_FakeResp("not json")):
        out = r.rewrite("foo")
    assert out == "foo"


def test_ollama_rewrite_strips_quotes_in_response():
    r = OllamaRewriter()
    body = json.dumps({"response": '"quoted output"'})
    with patch("urllib.request.urlopen", return_value=_FakeResp(body)):
        out = r.rewrite("query")
    assert out == "quoted output"
