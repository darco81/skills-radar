"""Tests for the LLM-based injection scanner."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from skills_radar.injection_scanner import (
    MLXScanner,
    NoOpScanner,
    OllamaScanner,
    _parse_classification,
    make_scanner,
)


def test_noop_passthrough():
    s = NoOpScanner()
    out = s.score("any body content")
    assert out["classification"] == "safe"


def test_factory_default():
    assert isinstance(make_scanner("none"), NoOpScanner)


def test_factory_ollama():
    s = make_scanner("ollama", url="http://x:1", model="m", timeout=1.0)
    assert isinstance(s, OllamaScanner)


def test_factory_mlx_platform_aware():
    import platform

    if platform.machine() != "arm64":
        with pytest.raises(RuntimeError, match="Apple Silicon"):
            make_scanner("mlx")
    else:
        s = make_scanner("mlx")
        assert isinstance(s, MLXScanner)
        assert s._loaded is False  # lazy


def test_factory_unknown():
    with pytest.raises(ValueError, match="Unknown injection scanner"):
        make_scanner("magic")


def test_url_validation():
    with pytest.raises(ValueError, match="http"):
        OllamaScanner(url="file:///tmp/evil")


def test_parse_classification_safe():
    out = _parse_classification('{"classification": "safe", "reason": "looks fine"}')
    assert out["classification"] == "safe"


def test_parse_classification_suspicious():
    out = _parse_classification(
        '{"classification": "suspicious", "reason": "instruction override pattern"}'
    )
    assert out["classification"] == "suspicious"
    assert "instruction override" in out["reason"]


def test_parse_classification_malicious():
    out = _parse_classification('{"classification": "malicious", "reason": "explicit"}')
    assert out["classification"] == "malicious"


def test_parse_classification_with_preamble():
    out = _parse_classification('Sure, here it is: {"classification": "suspicious", "reason": "x"}')
    assert out["classification"] == "suspicious"


def test_parse_classification_invalid_json():
    out = _parse_classification("not really a json with classification keyword")
    assert out["classification"] == "safe"  # default fail-safe
    assert out["confidence"] == 0.0


def test_parse_classification_unknown_class():
    out = _parse_classification('{"classification": "evil", "reason": "x"}')
    assert out["classification"] == "safe"  # unknown → default safe


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_ollama_score_success():
    s = OllamaScanner()
    body = '{"classification": "suspicious", "reason": "ignore previous instructions detected"}'
    with patch("urllib.request.urlopen", return_value=_FakeResp(json.dumps({"response": body}))):
        out = s.score("some body content")
    assert out["classification"] == "suspicious"


def test_ollama_score_network_error_falls_back_to_safe():
    s = OllamaScanner(timeout=0.1)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("boom")):
        out = s.score("body")
    assert out["classification"] == "safe"
    assert "scanner_error" in out["reason"]
