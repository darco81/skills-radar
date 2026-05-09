"""Config loading. YAML file at XDG location with sensible defaults."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


def _expand(p: str | Path) -> Path:
    return Path(str(p)).expanduser()


class EmbedderConfig(BaseModel):
    backend: str = "sentence-transformers"
    model: str = "all-MiniLM-L6-v2"


class StoreConfig(BaseModel):
    backend: str = "chromadb"
    path: Path = Field(default_factory=lambda: _expand("~/.local/share/skill-radar/store"))

    @field_validator("path", mode="before")
    @classmethod
    def _expand_path(cls, v: str | Path) -> Path:
        return _expand(v)


class TransportConfig(BaseModel):
    mode: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 6580
    http_path: str = "/mcp"
    stateless_http: bool = True
    json_response: bool = True


class RewriterConfig(BaseModel):
    backend: str = "none"  # 'none' | 'ollama'
    model: str = "gemma4:e4b"
    url: str = "http://localhost:11434"
    timeout: float = 5.0
    enabled: bool = False


class RetrievalConfig(BaseModel):
    hybrid_weight_semantic: float = 0.7
    hybrid_weight_lexical: float = 0.3
    default_top_k: int = 5
    rewriter: RewriterConfig = Field(default_factory=RewriterConfig)

    @field_validator("hybrid_weight_semantic", "hybrid_weight_lexical")
    @classmethod
    def _0_to_1(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = f"Weight must be between 0 and 1, got {v}"
            raise ValueError(msg)
        return v


class TrustConfig(BaseModel):
    default_tier: str = "user"
    trusted_paths: list[Path] = Field(default_factory=lambda: [_expand("~/.claude/skills")])

    @field_validator("trusted_paths", mode="before")
    @classmethod
    def _expand_each(cls, v: list[str | Path]) -> list[Path]:
        return [_expand(p) for p in v]


class SanitizationConfig(BaseModel):
    max_skill_size_kb: int = 64
    strip_xml_tags: bool = True
    strip_live_exec: bool = False  # Only strip for non-Claude-Code clients


class Config(BaseModel):
    paths: list[Path] = Field(
        default_factory=lambda: [
            _expand("~/.claude/skills"),
            _expand("~/.claude/plugins/cache/claude-plugins-official"),
        ]
    )
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    trust: TrustConfig = Field(default_factory=TrustConfig)
    sanitization: SanitizationConfig = Field(default_factory=SanitizationConfig)

    @field_validator("paths", mode="before")
    @classmethod
    def _expand_paths(cls, v: list[str | Path]) -> list[Path]:
        return [_expand(p) for p in v]

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load from YAML file, or return defaults if missing."""
        if path is None:
            path = cls.default_path()
        if not path.exists():
            logger.info("No config file at %s - using defaults", path)
            return cls()
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.info("Loaded config from %s", path)
        return cls(**data)

    @staticmethod
    def default_path() -> Path:
        return _expand("~/.config/skill-radar/config.yaml")
